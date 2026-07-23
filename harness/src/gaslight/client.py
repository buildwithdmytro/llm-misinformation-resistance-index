"""Thin LLM client abstraction shared by run.py (models under test) and judge.py.

litellm is imported lazily *inside* LiteLLMClient.complete so that importing this
module — and running the test suite — never requires litellm to be installed.
Tests inject a fake client implementing the same `complete` signature.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class Completion:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: Optional[float] = None
    latency_ms: Optional[float] = None
    raw: Any = None
    thinking: str = ""  # provider-exposed reasoning (diagnostic only; judges never see it)


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Completion:
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Rate-limit handling (429) — shared by run.py and judge.py retry loops
# ─────────────────────────────────────────────────────────────────────────────
def is_rate_limit_error(exc: BaseException) -> bool:
    """True if `exc` looks like a 429 / quota / rate-limit error from any provider."""
    if getattr(exc, "status_code", None) == 429 or getattr(exc, "code", None) == 429:
        return True
    name = type(exc).__name__.lower()
    if "ratelimit" in name:
        return True
    text = str(exc).lower()
    needles = ("429", "too many requests", "rate limit", "ratelimit",
               "resource exhausted", "quota exceeded", "resource_exhausted")
    return any(n in text for n in needles)


def retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Best-effort parse of a Retry-After hint from the exception (header or text)."""
    ra = getattr(exc, "retry_after", None)
    headers = getattr(exc, "headers", None)  # urllib.error.HTTPError carries headers
    if ra is None and headers is not None:
        try:
            ra = headers.get("Retry-After")
        except Exception:
            ra = None
    if ra is not None:
        try:
            return float(ra)
        except (TypeError, ValueError):
            pass
    m = re.search(r"retry[-_ ]?after[\"'\s:=]+(\d+(?:\.\d+)?)", str(exc), re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


def next_backoff(attempt: int, exc: BaseException, *, base_delay: float,
                 rl_base: float = 8.0, cap: float = 90.0) -> float:
    """Seconds to sleep before the next retry.

    `attempt` is 0-indexed (0 = after the first failure). Rate-limit errors get a
    much longer exponential backoff (and honor Retry-After when present); ordinary
    transient errors keep the caller's short exponential schedule.
    """
    if is_rate_limit_error(exc):
        delay = min(cap, rl_base * (2 ** attempt))
        ra = retry_after_seconds(exc)
        return max(delay, ra) if ra is not None else delay
    return min(cap, base_delay * (2 ** attempt))


class _Paced:
    """Mixin: enforce a minimum wall-clock interval between `complete` calls.

    Proactive spacing to stay under a provider's requests-per-minute cap. Uses a
    monotonic clock so it never goes backwards; `min_interval=0` disables it.
    """

    min_interval: float = 0.0
    _last_call: float = 0.0

    def _pace(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


class LiteLLMClient(_Paced):
    """Real client backed by litellm. Imported lazily to keep import cheap."""

    def __init__(self, *, timeout: float = 120.0, extra: Optional[dict] = None,
                 min_interval: float = 0.0):
        self.timeout = timeout
        self.extra = extra or {}
        self.min_interval = min_interval

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Completion:
        import litellm  # lazy

        self._pace()
        kwargs: dict[str, Any] = dict(model=model, messages=messages, timeout=self.timeout)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        kwargs.update(self.extra)

        t0 = time.perf_counter()
        resp = litellm.completion(**kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
        ct = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
        cost = None
        try:
            cost = litellm.completion_cost(completion_response=resp)
        except Exception:
            cost = None
        return Completion(
            text=text, prompt_tokens=pt, completion_tokens=ct,
            cost=cost, latency_ms=latency_ms, raw=resp,
        )


class VertexExpressClient(_Paced):
    """Client for Vertex AI **Express Mode** API keys (the ``AQ.`` keys).

    litellm's vertex path forces service-account / ADC auth, so express keys
    can't route through it. Express keys work only against the global endpoint
    (``aiplatform.googleapis.com``) with the key passed as ``?key=``. This client
    hits that endpoint directly over stdlib http — no extra deps, no ADC.

    The model string may carry a provider prefix (``vertex_ai/gemini-3.5-flash``);
    only the final path segment is sent to the endpoint.
    """

    BASE = "https://aiplatform.googleapis.com/v1/publishers/google/models"

    def __init__(self, api_key: Optional[str] = None, *, timeout: float = 300.0,
                 min_interval: float = 0.0, include_thoughts: bool = False):
        import os

        self.api_key = api_key or os.environ.get("VERTEX_EXPRESS_API_KEY")
        if not self.api_key:
            raise RuntimeError("VERTEX_EXPRESS_API_KEY not set")
        self.timeout = timeout
        self.min_interval = min_interval
        self.include_thoughts = include_thoughts

    def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Completion:
        import json
        import urllib.request

        self._pace()
        bare = model.split("/")[-1]
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in messages if m["role"] != "system"
        ]
        gen: dict[str, Any] = {}
        if temperature is not None:
            gen["temperature"] = temperature
        if max_tokens is not None:
            gen["maxOutputTokens"] = max_tokens
        body: dict[str, Any] = {"contents": contents}
        sys = [m["content"] for m in messages if m["role"] == "system"]
        if sys:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(sys)}]}
        if self.include_thoughts:
            gen["thinkingConfig"] = {"includeThoughts": True}
        if gen:
            body["generationConfig"] = gen

        url = f"{self.BASE}/{bare}:generateContent?key={self.api_key}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        latency_ms = (time.perf_counter() - t0) * 1000.0

        cand = (payload.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        thinking = "".join(p.get("text", "") for p in parts if p.get("thought"))
        usage = payload.get("usageMetadata") or {}
        return Completion(
            text=text,
            prompt_tokens=usage.get("promptTokenCount", 0) or 0,
            completion_tokens=usage.get("candidatesTokenCount", 0) or 0,
            cost=None,
            latency_ms=latency_ms,
            raw=payload,
            thinking=thinking,
        )


def make_client(model_id: str, *, min_interval: float = 0.0,
                include_thoughts: bool = False) -> LLMClient:
    """Pick the right client for a model id.

    ``vertex_ai/…`` routes to :class:`VertexExpressClient` when a
    ``VERTEX_EXPRESS_API_KEY`` is set (litellm 1.42.x can't auth express keys);
    everything else — including ``openrouter/…``, ``anthropic/…``, ``gpt-…`` —
    goes through :class:`LiteLLMClient`. ``min_interval`` proactively paces calls
    to stay under a provider's rate limit.
    """
    import os

    if model_id.startswith("vertex_ai/") and os.environ.get("VERTEX_EXPRESS_API_KEY"):
        return VertexExpressClient(min_interval=min_interval,
                                   include_thoughts=include_thoughts)
    return LiteLLMClient(min_interval=min_interval)


def model_slug(model: str) -> str:
    """Filesystem-safe slug for a model id."""
    out = []
    for ch in model:
        out.append(ch if (ch.isalnum() or ch in "-.") else "_")
    return "".join(out)
