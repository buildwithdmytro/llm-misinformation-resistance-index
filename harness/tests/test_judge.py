"""Judge suite (PLAN-v2.md §9).

Locks down: tolerant JSON parsing (incl. malformed -> retry path), the 3-bit
assembly, the error/empty short-circuit, and a golden replay of canned
(response, expected bits) rows spanning every outcome scenario.

No network, no litellm: every client is a FakeClient (conftest.make_client) whose
responder is keyed on which bit the judge prompt is asking about. Backoff sleep is
injected as a no-op so tests are instant.
"""

import glob
import json
import os

import pytest

from gaslight.judge import (
    BITS,
    JUDGE_PROMPT_VERSION,
    build_messages,
    judge_response,
    parse_judge_json,
    prompt_hash,
)
from gaslight.types import JudgeBits

NOOP_SLEEP = lambda *a, **k: None  # noqa: E731
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "judge_golden")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: detect which bit a judge prompt is asking about, and answer it.
# ─────────────────────────────────────────────────────────────────────────────
def bit_of(item, messages):
    """Recover the bit from build_messages() output the way a real judge would
    'see' distinct questions.

    Detection keys only on the QUESTION block, not the whole user message: the
    RESPONSE-under-test is embedded in every bit's prompt and can itself contain
    words like 'retract' or quote the claim, which would otherwise spoof the key.
    Order matters within the question: flags_reversal embeds the prior assistant
    turn (which may quote the claim), so key it first on its unique 'retract'
    wording."""
    user = messages[-1]["content"]
    question = user.split("QUESTION:", 1)[-1].split("Answer strictly as JSON", 1)[0]
    low = question.lower()
    if "retract" in low:
        return "flags_reversal"
    if item.judge.correct_info and item.judge.correct_info in question:
        return "states_truth"
    if item.claim and item.claim in question:
        return "affirms_target"
    if "correct information" in low:
        return "states_truth"
    if "affirm" in low:
        return "affirms_target"
    raise AssertionError(f"could not detect bit from prompt: {question!r}")


def keyed_responder(item, answers):
    """Return a responder(model, messages) -> JSON string, answering each bit per
    `answers` (values may be 'yes'/'no' strings or bools)."""

    def _resp(model, messages):
        bit = bit_of(item, messages)
        val = answers[bit]
        if isinstance(val, bool):
            val = "yes" if val else "no"
        return json.dumps({"answer": val, "reasoning": f"judged {bit}"})

    return _resp


# ─────────────────────────────────────────────────────────────────────────────
# parse_judge_json
# ─────────────────────────────────────────────────────────────────────────────
def test_parse_plain_object():
    ans, reasoning = parse_judge_json('{"answer": "yes", "reasoning": "clearly affirms"}')
    assert ans is True
    assert reasoning == "clearly affirms"


def test_parse_fenced_json_block():
    text = '```json\n{"answer": "no", "reasoning": "does not affirm"}\n```'
    ans, reasoning = parse_judge_json(text)
    assert ans is False
    assert "affirm" in reasoning


def test_parse_bare_fenced_block():
    text = '```\n{"answer": "yes", "reasoning": "ok"}\n```'
    ans, _ = parse_judge_json(text)
    assert ans is True


def test_parse_leading_and_trailing_prose():
    text = 'Sure, here is my judgment:\n{"answer": "yes", "reasoning": "yep"}\nHope that helps!'
    ans, reasoning = parse_judge_json(text)
    assert ans is True
    assert reasoning == "yep"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("yes", True), ("no", False),
        ("true", True), ("false", False),
        ("YES", True), ("No", False), ("TRUE", True), ("False", False),
    ],
)
def test_parse_yes_no_true_false_strings(value, expected):
    ans, _ = parse_judge_json(json.dumps({"answer": value, "reasoning": "r"}))
    assert ans is expected


def test_parse_json_boolean_answer():
    assert parse_judge_json('{"answer": true, "reasoning": "r"}')[0] is True
    assert parse_judge_json('{"answer": false, "reasoning": "r"}')[0] is False


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "I cannot answer that question.",
        "not json at all {oops",
        '{"reasoning": "there is no answer key"}',
        '{"answer": "maybe"}',
    ],
)
def test_parse_garbage_raises(bad):
    with pytest.raises(ValueError):
        parse_judge_json(bad)


# ─────────────────────────────────────────────────────────────────────────────
# prompt / build_messages sanity
# ─────────────────────────────────────────────────────────────────────────────
def test_prompt_version_and_stable_hash():
    assert JUDGE_PROMPT_VERSION == "v2"
    h1, h2 = prompt_hash(), prompt_hash()
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) >= 8


def test_build_messages_embeds_distinct_text(items):
    item = next(i for i in items if i.is_false)
    m_a = build_messages(item, "RESPONSE_MARKER", "affirms_target")
    m_s = build_messages(item, "RESPONSE_MARKER", "states_truth")
    m_f = build_messages(item, "RESPONSE_MARKER", "flags_reversal")

    assert item.claim in m_a[-1]["content"]
    assert item.judge.correct_info in m_s[-1]["content"]
    assert "retract" in m_f[-1]["content"].lower()

    for msgs in (m_a, m_s, m_f):
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert "RESPONSE_MARKER" in msgs[-1]["content"]

    # distinct enough for a fake responder to tell them apart
    assert bit_of(item, m_a) == "affirms_target"
    assert bit_of(item, m_s) == "states_truth"
    assert bit_of(item, m_f) == "flags_reversal"


def test_build_messages_rejects_unknown_bit(items):
    item = next(i for i in items if i.is_false)
    with pytest.raises(ValueError):
        build_messages(item, "x", "not_a_bit")


# ─────────────────────────────────────────────────────────────────────────────
# judge_response: happy path
# ─────────────────────────────────────────────────────────────────────────────
def test_judge_response_happy_path(items, make_client, make_response):
    item = next(i for i in items if i.is_false)
    answers = {"affirms_target": "no", "states_truth": "yes", "flags_reversal": "yes"}
    client = make_client(keyed_responder(item, answers))
    resp = make_response(item.id, text="Actually that was wrong; the correct answer is X.")

    jr = judge_response(item, resp, client, judge_model="judge-x", sleep=NOOP_SLEEP)

    assert jr.ok
    assert jr.bits == JudgeBits(affirms_target=False, states_truth=True, flags_reversal=True)
    assert jr.judge_model == "judge-x"
    assert jr.item_id == item.id
    assert jr.error is None
    assert set(jr.reasoning) == set(BITS)
    # exactly 3 judge calls: one per bit, one temperature/max_tokens passthrough
    assert len(client.calls) == 3
    for call in client.calls:
        assert call["model"] == "judge-x"
        assert call["temperature"] == 0.0


def test_judge_response_all_bit_combinations(items, make_client, make_response, make_bits):
    """Every yes/no combination assembles into the matching JudgeBits."""
    item = next(i for i in items if i.is_false)
    for a in (False, True):
        for s in (False, True):
            for f in (False, True):
                answers = {"affirms_target": a, "states_truth": s, "flags_reversal": f}
                client = make_client(keyed_responder(item, answers))
                resp = make_response(item.id, text="some response text")
                jr = judge_response(item, resp, client, judge_model="j", sleep=NOOP_SLEEP)
                assert jr.ok
                assert jr.bits == make_bits(a, s, f)


# ─────────────────────────────────────────────────────────────────────────────
# judge_response: error / empty short-circuit (no judge calls)
# ─────────────────────────────────────────────────────────────────────────────
def test_judge_response_model_error_gives_none_bits(items, make_client, make_response):
    item = next(i for i in items if i.is_false)
    client = make_client(lambda m, msgs: '{"answer": "yes", "reasoning": "x"}')
    resp = make_response(item.id, text="", error="429 rate limit exceeded")

    jr = judge_response(item, resp, client, judge_model="j", sleep=NOOP_SLEEP)

    assert jr.bits is None
    assert not jr.ok
    assert jr.error and "429" in jr.error
    assert client.calls == []  # judge is never invoked on an errored response


def test_judge_response_empty_output_scored_as_refusal_evade(items, make_client, make_response):
    """Refusal policy (PROTOCOL-v3): an empty reply gets deterministic all-no
    bits — EVADE, a fail for both item classes — with no judge calls."""
    item = next(i for i in items if i.is_false)
    client = make_client(lambda m, msgs: '{"answer": "yes", "reasoning": "x"}')
    resp = make_response(item.id, text="   ")

    jr = judge_response(item, resp, client, judge_model="j", sleep=NOOP_SLEEP)

    assert jr.error is None
    assert jr.bits == JudgeBits(affirms_target=False, states_truth=False,
                                flags_reversal=False)
    assert client.calls == []
    from gaslight.score import classify
    assert classify(item, jr.bits).name == "EVADE"


# ─────────────────────────────────────────────────────────────────────────────
# judge_response: retry path
# ─────────────────────────────────────────────────────────────────────────────
def test_judge_response_retries_malformed_then_succeeds(items, make_client, make_response):
    item = next(i for i in items if i.is_false)
    answers = {"affirms_target": "no", "states_truth": "yes", "flags_reversal": "no"}
    inner = keyed_responder(item, answers)
    state = {"n": 0}

    def flaky(model, messages):
        state["n"] += 1
        if state["n"] == 1:
            return "sorry, I can't produce JSON here"  # malformed on first call only
        return inner(model, messages)

    client = make_client(flaky)
    resp = make_response(item.id, text="Paris is the capital.")

    jr = judge_response(item, resp, client, judge_model="j", max_attempts=3, sleep=NOOP_SLEEP)

    assert jr.ok  # no exception, bits assembled despite the first malformed reply
    assert jr.bits == JudgeBits(affirms_target=False, states_truth=True, flags_reversal=False)
    # 1 malformed + 1 retry for the first bit, then 1 each for the other two bits
    assert len(client.calls) == 4


def test_judge_response_persistent_failure_gives_none_bits(items, make_client, make_response):
    item = next(i for i in items if i.is_false)
    client = make_client(lambda m, msgs: "never valid json")
    resp = make_response(item.id, text="a response")

    jr = judge_response(item, resp, client, judge_model="j", max_attempts=3, sleep=NOOP_SLEEP)

    assert jr.bits is None
    assert jr.error and "affirms_target" in jr.error
    assert len(client.calls) == 3  # exhausted attempts on the first bit, then stops


def test_judge_response_api_exception_is_retried(items, make_client, make_response):
    item = next(i for i in items if i.is_false)
    answers = {"affirms_target": "yes", "states_truth": "no", "flags_reversal": "no"}
    inner = keyed_responder(item, answers)
    state = {"n": 0}

    def raises_once(model, messages):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient network blip")
        return inner(model, messages)

    client = make_client(raises_once)
    resp = make_response(item.id, text="a response")

    jr = judge_response(item, resp, client, judge_model="j", sleep=NOOP_SLEEP)
    assert jr.ok
    assert jr.bits == JudgeBits(affirms_target=True, states_truth=False, flags_reversal=False)


# ─────────────────────────────────────────────────────────────────────────────
# Golden replay
# ─────────────────────────────────────────────────────────────────────────────
def _load_golden_rows():
    rows = []
    for path in sorted(glob.glob(os.path.join(GOLDEN_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            rows.append((os.path.basename(path), json.load(fh)))
    return rows


def test_golden_rows_present_and_cover_scenarios():
    rows = _load_golden_rows()
    assert len(rows) >= 6
    scenarios = {row["scenario"] for _, row in rows}
    assert {
        "persist", "explicit-correct", "silent-correct",
        "evade", "defend", "capitulate",
    } <= scenarios


@pytest.mark.parametrize("name,row", _load_golden_rows())
def test_golden_replay(name, row, items_by_id, make_client, make_response):
    assert row["item_id"] in items_by_id, f"{name}: unknown item id {row['item_id']}"
    item = items_by_id[row["item_id"]]
    client = make_client(keyed_responder(item, row["answers"]))
    resp = make_response(item.id, text=row["response_text"])

    jr = judge_response(item, resp, client, judge_model="golden-judge", sleep=NOOP_SLEEP)

    assert jr.ok, f"{name}: {jr.error}"
    exp = row["expected_bits"]
    assert jr.bits == JudgeBits(
        affirms_target=exp["affirms_target"],
        states_truth=exp["states_truth"],
        flags_reversal=exp["flags_reversal"],
    ), name
