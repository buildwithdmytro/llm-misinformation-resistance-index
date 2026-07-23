"""Execution harness: run items × models × samples, resumable, with a run manifest.

See docs/CONTRACT.md §run.py. This module performs I/O (writing JSONL + manifest)
and takes an injected `LLMClient` so tests never hit the network. The library
functions here are deterministic: the ONLY wall-clock timestamp is a
caller-supplied `started_at` (main() stamps one; the library never reads the clock).

litellm is never imported at module load — `main()` constructs a LiteLLMClient
lazily only when no client is injected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from .client import LLMClient, model_slug
from .data import REPO_ROOT, load_items
from .types import Item, ModelResponse

DEFAULT_SAMPLES = 3


# ─────────────────────────────────────────────────────────────────────────────
# Run manifest
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RunManifest:
    dataset_version: str          # parsed from dataset/CHANGELOG.md (or "unknown")
    n_items: int
    models: list[dict]            # requested config, incl. temperature/max_tokens
    judge: dict                   # judge config echoed
    samples: int
    started_at: Optional[str] = None   # caller-supplied ISO timestamp (no wall-clock in lib)
    seed: Optional[int] = None
    resolved_models: dict = field(default_factory=dict)  # requested id -> id returned by API

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def dataset_version(changelog_path: str | None = None) -> str:
    """Best-effort dataset version from the first `## vX.Y[.Z]` heading of the CHANGELOG."""
    path = changelog_path or os.path.join(REPO_ROOT, "dataset", "CHANGELOG.md")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^#+\s*(v?\d+\.\d+(?:\.\d+)?)", line.strip())
                if m:
                    return m.group(1)
    except OSError:
        pass
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Retry / resume primitives
# ─────────────────────────────────────────────────────────────────────────────
def with_retries(fn: Callable[[], Any], *, max_attempts: int = 5,
                 base_delay: float = 0.5, sleep: Callable[[float], Any] = time.sleep) -> Any:
    """Call `fn` with exponential backoff; re-raise the last error after `max_attempts`.

    `sleep` is injectable so tests never actually wait. No sleep after the final
    (failing) attempt.
    """
    from .client import next_backoff

    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — retry any transient failure
            last_exc = exc
            if attempt < max_attempts - 1:
                sleep(next_backoff(attempt, exc, base_delay=base_delay))
    assert last_exc is not None
    raise last_exc


def completed_keys(jsonl_path: str) -> set[tuple[str, int]]:
    """(item_id, sample_idx) pairs already recorded in an output file (for resume)."""
    keys: set[tuple[str, int]] = set()
    if not os.path.exists(jsonl_path):
        return keys
    with open(jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            keys.add((d["item_id"], int(d["sample_idx"])))
    return keys


# ─────────────────────────────────────────────────────────────────────────────
# Running one model over the item set
# ─────────────────────────────────────────────────────────────────────────────
def run_model(model_cfg: dict, items: list[Item], client: LLMClient, out_path: str, *,
              samples: int, defaults: dict, resume: bool = True,
              max_attempts: int = 5, base_delay: float = 0.5,
              sleep: Callable[[float], Any] = time.sleep) -> dict:
    """Run one model over `items` × `samples`, appending one ModelResponse per line.

    Each (item, sample) not already present (when resuming) is completed via
    `client.complete`, wrapped in `with_retries`. A sample that never succeeds is
    still WRITTEN as a ModelResponse with `error` set — never dropped.

    Returns counts: {"written", "errors", "skipped", "resolved_model"}.

    `max_attempts`/`base_delay`/`sleep` are forwarded to `with_retries` (additive to
    the contract signature so tests can make retries instant).
    """
    model = model_cfg["id"]
    temperature = model_cfg.get("temperature", defaults.get("temperature"))
    max_tokens = model_cfg.get("max_tokens", defaults.get("max_tokens"))

    done = completed_keys(out_path) if resume else set()

    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    counts = {"written": 0, "errors": 0, "skipped": 0}
    resolved_model: Optional[str] = None

    with open(out_path, "a", encoding="utf-8") as fh:
        for item in items:
            messages = item.messages()
            for sample_idx in range(samples):
                key = (item.id, sample_idx)
                if key in done:
                    counts["skipped"] += 1
                    continue

                def call(m=model, msgs=messages, temp=temperature, mt=max_tokens):
                    return client.complete(m, msgs, temperature=temp, max_tokens=mt)

                try:
                    comp = with_retries(call, max_attempts=max_attempts,
                                        base_delay=base_delay, sleep=sleep)
                    if resolved_model is None:
                        resolved_model = getattr(comp.raw, "model", None) or model
                    resp = ModelResponse(
                        item_id=item.id, model=model, sample_idx=sample_idx,
                        output_text=comp.text, latency_ms=comp.latency_ms,
                        prompt_tokens=comp.prompt_tokens,
                        completion_tokens=comp.completion_tokens,
                        cost=comp.cost, error=None,
                    )
                except Exception as exc:  # noqa: BLE001 — record, never drop
                    resp = ModelResponse(
                        item_id=item.id, model=model, sample_idx=sample_idx,
                        output_text="", error=f"{type(exc).__name__}: {exc}",
                    )
                    counts["errors"] += 1

                fh.write(json.dumps(resp.to_dict()) + "\n")
                fh.flush()
                counts["written"] += 1
                done.add(key)

    counts["resolved_model"] = resolved_model
    return counts


def _model_manifest_entry(model_cfg: dict, defaults: dict) -> dict:
    """Requested model config enriched with the resolved temperature/max_tokens."""
    return {
        "id": model_cfg["id"],
        "provider": model_cfg.get("provider"),
        "temperature": model_cfg.get("temperature", defaults.get("temperature")),
        "max_tokens": model_cfg.get("max_tokens", defaults.get("max_tokens")),
    }


def write_manifest(manifest: RunManifest, results_dir: str) -> str:
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(results_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest.to_dict(), fh, indent=2, sort_keys=True)
    return path


def run_all(config: dict, items: list[Item], client: Optional[LLMClient],
            results_dir: str, *, resume: bool = True,
            started_at: str | None = None, pace: float = 0.0) -> dict:
    """Run every model in `config` over `items`, then write results/manifest.json.

    If `client` is None, an appropriate client is built per model via
    :func:`client.make_client` (routing express vs. litellm by model id) with the
    given `pace` (min seconds between calls). If `client` is supplied it is used
    for every model verbatim — tests inject a fake client this way.

    `started_at` (or config["started_at"]) is the only place a wall-clock string
    enters the manifest, and it is supplied by the caller — the library never reads
    the clock itself.
    """
    from .client import make_client

    defaults = dict(config.get("defaults", {}) or {})
    samples = int(defaults.get("samples", DEFAULT_SAMPLES))
    models = list(config.get("models", []) or [])

    raw_dir = os.path.join(results_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    per_model: dict[str, dict] = {}
    resolved: dict[str, str] = {}
    for model_cfg in models:
        model = model_cfg["id"]
        slug = model_slug(model)
        model_client = client if client is not None else make_client(model, min_interval=pace)
        out_path = os.path.join(raw_dir, f"{slug}.responses.jsonl")
        counts = run_model(model_cfg, items, model_client, out_path,
                           samples=samples, defaults=defaults, resume=resume)
        per_model[model] = counts
        if counts.get("resolved_model"):
            resolved[model] = counts["resolved_model"]

    manifest = RunManifest(
        dataset_version=dataset_version(),
        n_items=len(items),
        models=[_model_manifest_entry(mc, defaults) for mc in models],
        judge=dict(config.get("judge", {}) or {}),
        samples=samples,
        started_at=started_at if started_at is not None else config.get("started_at"),
        seed=config.get("seed"),
        resolved_models=resolved,
    )
    write_manifest(manifest, results_dir)
    return {"models": per_model, "manifest": manifest.to_dict()}


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _load_yaml(path: str) -> dict:
    import yaml  # local import keeps run.py cheap for non-CLI importers
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve_judge_config(config: dict, config_path: str) -> dict:
    """Echo judge config: inline config['judge'] wins, else a sibling judge.yaml."""
    inline = config.get("judge")
    if inline:
        return dict(inline)
    judge_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), "judge.yaml")
    if os.path.exists(judge_path):
        return _load_yaml(judge_path)
    return {}


def main(argv: list[str] | None = None, client: LLMClient | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gaslight.run",
                                     description="Run the Gaslighting Index item sweep.")
    parser.add_argument("--config", default="configs/models.yaml",
                        help="models config YAML (defaults + models list).")
    parser.add_argument("--models", default=None,
                        help="comma-separated model ids to restrict the run to.")
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N items (smoke tests).")
    parser.add_argument("--no-resume", action="store_true",
                        help="ignore existing output; re-run every (item, sample).")
    parser.add_argument("--results-dir", default="results",
                        help="output directory (raw/ + manifest.json).")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed recorded in the manifest.")
    parser.add_argument("--pace", type=float, default=0.0,
                        help="min seconds between API calls per model (rate-limit "
                             "throttle; e.g. 6 for the Vertex Express free tier).")
    args = parser.parse_args(argv)

    config = _load_yaml(args.config)
    config["judge"] = _resolve_judge_config(config, args.config)
    if args.seed is not None:
        config["seed"] = args.seed

    if args.models:
        wanted = {m.strip() for m in args.models.split(",") if m.strip()}
        config["models"] = [m for m in config.get("models", []) if m["id"] in wanted]

    items = load_items()
    if args.limit is not None:
        items = items[: args.limit]

    # When no client is injected (real CLI), run_all builds one per model via
    # make_client — routing express vs. litellm by model id. Tests inject a client.

    # The single, caller-owned wall-clock stamp. Library stays deterministic.
    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc).isoformat()

    run_all(config, items, client, args.results_dir,
            resume=not args.no_resume, started_at=started_at, pace=args.pace)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
