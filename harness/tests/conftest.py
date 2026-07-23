"""Shared pytest fixtures. No network, no litellm.

Every suite that needs an LLM client uses `make_client(responder)` to build a
FakeClient; `responder(model, messages)` returns either a str or a
gaslight.client.Completion.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from gaslight.client import Completion  # noqa: E402
from gaslight.data import load_items  # noqa: E402
from gaslight.types import JudgeBits, JudgeResult, ModelResponse  # noqa: E402


@pytest.fixture(scope="session")
def items():
    return load_items()


@pytest.fixture(scope="session")
def items_by_id(items):
    return {it.id: it for it in items}


class FakeClient:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def complete(self, model, messages, *, temperature=None, max_tokens=None):
        self.calls.append(
            {"model": model, "messages": messages,
             "temperature": temperature, "max_tokens": max_tokens}
        )
        out = self.responder(model, messages)
        if isinstance(out, Completion):
            return out
        return Completion(text=out, prompt_tokens=10, completion_tokens=20,
                          cost=0.0, latency_ms=1.0)


@pytest.fixture
def make_client():
    def _make(responder):
        return FakeClient(responder)
    return _make


@pytest.fixture
def make_response():
    def _make(item_id, *, model="test-model", sample_idx=0, text="ok", error=None,
              prompt_tokens=10, completion_tokens=20):
        return ModelResponse(item_id=item_id, model=model, sample_idx=sample_idx,
                             output_text=text, error=error,
                             prompt_tokens=prompt_tokens,
                             completion_tokens=completion_tokens)
    return _make


@pytest.fixture
def make_bits():
    def _make(affirms_target, states_truth, flags_reversal):
        return JudgeBits(affirms_target=affirms_target, states_truth=states_truth,
                         flags_reversal=flags_reversal)
    return _make


@pytest.fixture
def make_judge_result():
    def _make(item_id, bits, *, model="test-model", sample_idx=0,
              judge_model="judge", error=None):
        return JudgeResult(item_id=item_id, model=model, sample_idx=sample_idx,
                           bits=bits, judge_model=judge_model, error=error)
    return _make
