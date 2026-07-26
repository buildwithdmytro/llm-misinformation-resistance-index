"""Escalation protocol (gaslight.escalation) — offline, fake clients only."""

import json

import pytest

from gaslight.escalation import (
    PRESSURE_ROUNDS,
    judge_escalation,
    run_escalation,
    score_escalation,
)

NOOP = lambda _d: None  # noqa: E731


@pytest.fixture
def false_item(items):
    return next(i for i in items if i.is_false)


@pytest.fixture
def control_item(items):
    return next(i for i in items if not i.is_false)


# ─────────────────────────────────────────────────────────────────────────────
# run_escalation
# ─────────────────────────────────────────────────────────────────────────────
def test_run_writes_one_row_per_round(make_client, false_item, tmp_path):
    client = make_client(lambda m, msgs: f"reply after {len(msgs)} msgs")
    out = tmp_path / "m.escalation.jsonl"
    counts = run_escalation({"id": "m"}, [false_item], client, str(out),
                            samples=1, defaults={}, sleep=NOOP)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert counts["written"] == len(PRESSURE_ROUNDS) + 1
    assert [r["round"] for r in rows] == list(range(len(PRESSURE_ROUNDS) + 1))
    # each later round sees 2 more messages (assistant reply + pressure turn)
    lens = [c["messages"] for c in client.calls]
    assert all(len(lens[i + 1]) == len(lens[i]) + 2 for i in range(len(lens) - 1))
    # pressure turns are the scripted ladder, in order
    last_users = [c["messages"][-1]["content"] for c in client.calls[1:]]
    assert last_users == PRESSURE_ROUNDS


def test_run_resumes_mid_chain_without_duplicates(make_client, false_item, tmp_path):
    out = tmp_path / "m.escalation.jsonl"
    boom = {"n": 0}

    def flaky(model, messages):
        boom["n"] += 1
        if boom["n"] > 2:  # succeed twice (rounds 0,1), then die hard
            raise RuntimeError("network down")
        return "held"

    client = make_client(flaky)
    run_escalation({"id": "m"}, [false_item], client, str(out),
                   samples=1, defaults={}, max_attempts=1, sleep=NOOP)
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r["round"] for r in rows] == [0, 1, 2]
    assert rows[2]["error"]  # the failed round is recorded, chain stops

    # resume with a healthy client: rounds 0-1 skipped, 2.. re-run? No — an
    # errored round is terminal for the chain on resume too (row exists).
    client2 = make_client(lambda m, msgs: "held")
    counts = run_escalation({"id": "m"}, [false_item], client2, str(out),
                            samples=1, defaults={}, sleep=NOOP)
    assert counts["written"] == 0
    assert len(out.read_text().splitlines()) == 3  # no duplicates


# ─────────────────────────────────────────────────────────────────────────────
# judge + score, end to end on fakes
# ─────────────────────────────────────────────────────────────────────────────
def _write_rows(path, item_id, replies, model="m", sample_idx=0):
    with open(path, "w") as fh:
        for rnd, text in enumerate(replies):
            fh.write(json.dumps({"item_id": item_id, "model": model,
                                 "sample_idx": sample_idx, "round": rnd,
                                 "output_text": text, "error": None}) + "\n")


def test_judge_and_score_fold_at_round_2(make_client, items_by_id, false_item, tmp_path):
    n = len(PRESSURE_ROUNDS) + 1
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, false_item.id, ["r%d" % i for i in range(n)])

    def judge_fn(model, messages):
        text = messages[-1]["content"]
        if "affirms_target" in text or "states_truth" in text or "flags_reversal" in text:
            # v2 3-bit calls on round 0: explicit correct
            if "affirms_target" in text:
                return '{"answer": "no", "reasoning": "corrects"}'
            return '{"answer": "yes", "reasoning": "explicit"}'
        # binary fold calls: reply r2 onwards affirms
        folds = any(f"\nr{k}\n" in text or f"---\nr{k}\n" in text for k in (2, 3, 4))
        return json.dumps({"answer": "yes" if folds else "no", "reasoning": "x"})

    jc = make_client(judge_fn)
    jpath = tmp_path / "m.escalation.judge.jsonl"
    n_judged = judge_escalation(items_by_id, str(resp), str(jpath), jc,
                                judge_model="j", sleep=NOOP)
    assert n_judged == n
    result = score_escalation(items_by_id, str(jpath), n_rounds=len(PRESSURE_ROUNDS))
    # folded at round 2 -> endurance 2/5 = 40%
    assert result["resistance_endurance"] == 40.0
    assert result["strict_pass_rate_false"] == 0.0

    # judging is resumable: second call judges nothing new
    assert judge_escalation(items_by_id, str(resp), str(jpath), jc,
                            judge_model="j", sleep=NOOP) == 0


def test_score_survivor_needs_explicit_round0(make_client, items_by_id, false_item, tmp_path):
    n = len(PRESSURE_ROUNDS) + 1
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, false_item.id, ["held"] * n)

    def judge_silent(model, messages):
        text = messages[-1]["content"]
        if "affirms_target" in text:
            return '{"answer": "no", "reasoning": "x"}'
        if "states_truth" in text:
            return '{"answer": "yes", "reasoning": "x"}'
        if "flags_reversal" in text:
            return '{"answer": "no", "reasoning": "x"}'  # SILENT_CORRECT
        return '{"answer": "no", "reasoning": "never folds"}'

    jpath = tmp_path / "m.escalation.judge.jsonl"
    judge_escalation(items_by_id, str(resp), str(jpath),
                     make_client(judge_silent), judge_model="j", sleep=NOOP)
    result = score_escalation(items_by_id, str(jpath), n_rounds=len(PRESSURE_ROUNDS))
    assert result["resistance_endurance"] == 100.0     # never folded...
    assert result["strict_pass_rate_false"] == 0.0     # ...but silent -> no strict pass


def test_control_item_uses_retract_judgment(make_client, items_by_id, control_item, tmp_path):
    n = len(PRESSURE_ROUNDS) + 1
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, control_item.id, ["held"] * n)

    seen = {"retract": 0}

    def judge_fn(model, messages):
        text = messages[-1]["content"]
        if "Which position" in text:  # v4 control prompt
            seen["retract"] += 1
            return '{"reasoning": "held", "answer": "kept"}'
        return '{"answer": "no", "reasoning": "x"}'

    jpath = tmp_path / "m.escalation.judge.jsonl"
    judge_escalation(items_by_id, str(resp), str(jpath),
                     make_client(judge_fn), judge_model="j", sleep=NOOP)
    assert seen["retract"] == n  # every round judged with the control question
    result = score_escalation(items_by_id, str(jpath), n_rounds=len(PRESSURE_ROUNDS))
    assert result["steadfastness_endurance"] == 100.0
    assert result["strict_pass_rate_controls"] == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# inline judging: early-exit + adaptive sampling (PROTOCOL-v3 cost levers)
# ─────────────────────────────────────────────────────────────────────────────
def test_inline_early_exit_and_adaptive_skip(make_client, false_item, tmp_path):
    """Model folds at round 1 on every sample: the chain stops at round 1 and
    samples 2-3 are skipped entirely (the strict gate is already decided)."""
    gen = make_client(lambda m, msgs: f"reply{len(msgs)}")

    def judge_fn(model, messages):
        text = messages[-1]["content"]
        folds = "reply" in text and "FINAL ASSISTANT REPLY TO GRADE" in text and \
            any(f"reply{k}" in text.split("FINAL ASSISTANT REPLY TO GRADE")[-1]
                for k in (5, 6, 7, 8, 9, 10, 11, 12))  # round>=1 has >=5 msgs
        return json.dumps({"answer": "yes" if folds else "no", "reasoning": "x"})

    jc = make_client(judge_fn)
    out = tmp_path / "m.escalation.jsonl"
    jpath = tmp_path / "m.escalation.judge.jsonl"
    counts = run_escalation({"id": "m"}, [false_item], gen, str(out),
                            samples=3, defaults={}, sleep=NOOP,
                            judge_client=jc, judge_model="j", judge_path=str(jpath))
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    # sample 0 ran rounds 0 and 1 (fold at 1) and stopped; samples 1-2 skipped
    assert [r["round"] for r in rows] == [0, 1]
    assert counts["early_exits"] == 1
    assert counts["samples_skipped"] == 2
    jrows = [json.loads(l) for l in jpath.read_text().splitlines()]
    assert [j["folds"] for j in jrows] == [False, True]


def test_inline_survivor_runs_all_samples(make_client, false_item, tmp_path):
    gen = make_client(lambda m, msgs: "held")
    jc = make_client(lambda m, msgs: '{"answer": "no", "reasoning": "held"}')
    out = tmp_path / "m.escalation.jsonl"
    jpath = tmp_path / "m.escalation.judge.jsonl"
    counts = run_escalation({"id": "m"}, [false_item], gen, str(out),
                            samples=2, defaults={}, sleep=NOOP,
                            judge_client=jc, judge_model="j", judge_path=str(jpath))
    n = len(PRESSURE_ROUNDS) + 1
    assert counts["written"] == 2 * n          # both samples, full ladders
    assert counts["early_exits"] == 0
    assert counts["samples_skipped"] == 0
    # inline judge rows cover every generated row; resumable second call is a no-op
    assert len(jpath.read_text().splitlines()) == 2 * n
    counts2 = run_escalation({"id": "m"}, [false_item], gen, str(out),
                             samples=2, defaults={}, sleep=NOOP,
                             judge_client=jc, judge_model="j", judge_path=str(jpath))
    assert counts2["written"] == 0
    assert len(jpath.read_text().splitlines()) == 2 * n


# ─────────────────────────────────────────────────────────────────────────────
# v4 control judging (retract-judge-v4: position labels, reasoning-first)
# ─────────────────────────────────────────────────────────────────────────────
def test_parse_position_json():
    from gaslight.escalation import parse_position_json

    assert parse_position_json(
        '{"reasoning": "stands firm", "answer": "kept"}') == ("kept", "stands firm")
    assert parse_position_json(
        '```json\n{"reasoning": "caved", "answer": "retracted"}\n```')[0] == "retracted"
    assert parse_position_json('{"answer": "neither", "reasoning": null}')[0] == "neither"
    # regex fallback survives malformed JSON around a recognizable answer
    assert parse_position_json('{"reasoning": "bad \\escape", "answer": "kept"}')[0] == "kept"
    with pytest.raises(ValueError):
        parse_position_json('{"answer": "yes", "reasoning": "v3-style is rejected"}')


def test_control_retraction_scores_as_fold(make_client, items_by_id, control_item, tmp_path):
    n = len(PRESSURE_ROUNDS) + 1
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, control_item.id, ["held"] * n)

    def judge_fn(model, messages):
        if "Which position" in messages[-1]["content"]:
            return '{"reasoning": "caved", "answer": "retracted"}'
        return '{"answer": "no", "reasoning": "x"}'

    jpath = tmp_path / "m.escalation.judge.jsonl"
    judge_escalation(items_by_id, str(resp), str(jpath),
                     make_client(judge_fn), judge_model="j", sleep=NOOP)
    rows = [json.loads(l) for l in jpath.read_text().splitlines()]
    ctl = [r for r in rows if r["item_id"] == control_item.id]
    assert all(r["folds"] for r in ctl)
    assert all(r["judge_prompt_version"] == "retract-judge-v4" for r in ctl)
    assert all(r["position"] == "retracted" for r in ctl)
    result = score_escalation(items_by_id, str(jpath), n_rounds=len(PRESSURE_ROUNDS))
    assert result["steadfastness_endurance"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# empty replies fold (they are not survived rounds)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_empty_reply_folds_without_a_judge_call(make_client, items_by_id,
                                                false_item, tmp_path, blank):
    """A blank round-2 reply ends the chain, and the judge is never asked."""
    n = len(PRESSURE_ROUNDS) + 1
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, false_item.id,
                ["held"] * 2 + [blank] + ["held"] * (n - 3))

    calls = []

    def judge_fn(model, messages):
        calls.append(messages[-1]["content"])
        return '{"answer": "no", "reasoning": "held"}'

    jpath = tmp_path / "m.escalation.judge.jsonl"
    judge_escalation(items_by_id, str(resp), str(jpath),
                     make_client(judge_fn), judge_model="j", sleep=NOOP)
    rows = {r["round"]: r for r in
            (json.loads(l) for l in jpath.read_text().splitlines())}

    assert rows[2]["folds"] is True
    assert rows[2]["empty_reply"] is True
    assert rows[2]["error"] is None
    assert not any(r.get("empty_reply") for rd, r in rows.items() if rd != 2)
    # the blank reply is graded by rule, so it costs no round-judge call
    assert not any(blank.strip() == c.strip() for c in calls)

    result = score_escalation(items_by_id, str(jpath),
                              n_rounds=len(PRESSURE_ROUNDS))
    # two survived rounds out of five
    assert result["resistance_endurance"] == pytest.approx(40.0)


def test_all_empty_chain_scores_zero_endurance(make_client, items_by_id,
                                               false_item, tmp_path):
    """The kimi-k2.6 case: a chain that never said anything survives nothing."""
    n = len(PRESSURE_ROUNDS) + 1
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, false_item.id, [""] * n)

    jpath = tmp_path / "m.escalation.judge.jsonl"
    judge_escalation(items_by_id, str(resp), str(jpath),
                     make_client(lambda m, msgs: '{"answer": "no", "reasoning": "x"}'),
                     judge_model="j", sleep=NOOP)

    result = score_escalation(items_by_id, str(jpath),
                              n_rounds=len(PRESSURE_ROUNDS))
    assert result["resistance_endurance"] == 0.0
    assert result["strict_pass_rate_false"] == 0.0


def test_empty_control_reply_folds_with_sentinel_position(make_client, items_by_id,
                                                          control_item, tmp_path):
    """Controls get position='empty' — outside the judge's own vocabulary."""
    resp = tmp_path / "m.escalation.jsonl"
    _write_rows(resp, control_item.id, [""])

    jpath = tmp_path / "m.escalation.judge.jsonl"
    judge_escalation(items_by_id, str(resp), str(jpath),
                     make_client(lambda m, msgs: '{"reasoning": "x", "answer": "kept"}'),
                     judge_model="j", sleep=NOOP)
    row = json.loads(jpath.read_text().splitlines()[0])

    assert row["folds"] is True
    assert row["position"] == "empty"
    assert row["judge_prompt_version"] == "retract-judge-v4"
