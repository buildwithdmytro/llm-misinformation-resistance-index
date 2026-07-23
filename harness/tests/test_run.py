"""Execution-harness suite (PLAN-v2.md §9, CONTRACT §run.py).

Locks: resume-after-crash produces an identical result set (no duplicates),
retry/backoff with an injected sleep, error samples recorded not dropped, and a
manifest written by the CLI with an injected fake client (no network).
"""

import json

import pytest

from gaslight.run import (
    RunManifest,
    completed_keys,
    main,
    run_all,
    run_model,
    with_retries,
)


def _lines(path):
    text = path.read_text().strip()
    return text.splitlines() if text else []


def _records(path):
    return [json.loads(line) for line in _lines(path)]


# ─────────────────────────────────────────────────────────────────────────────
# with_retries
# ─────────────────────────────────────────────────────────────────────────────
def test_with_retries_succeeds_after_k_failures():
    calls = {"n": 0}
    sleeps = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:  # fail twice, then succeed
            raise ValueError("transient")
        return "value"

    result = with_retries(fn, max_attempts=5, base_delay=0.01,
                          sleep=lambda _d: sleeps.__setitem__("n", sleeps["n"] + 1))

    assert result == "value"
    assert calls["n"] == 3
    assert sleeps["n"] == 2  # one sleep before each of the two retries


def test_with_retries_raises_after_max_attempts():
    calls = {"n": 0}
    sleeps = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError):
        with_retries(fn, max_attempts=4, base_delay=0.01,
                     sleep=lambda _d: sleeps.__setitem__("n", sleeps["n"] + 1))

    assert calls["n"] == 4          # exactly max_attempts tries
    assert sleeps["n"] == 3         # no sleep after the final failing attempt


# ─────────────────────────────────────────────────────────────────────────────
# completed_keys
# ─────────────────────────────────────────────────────────────────────────────
def test_completed_keys_parses_written_file(tmp_path):
    out = tmp_path / "f.responses.jsonl"
    recs = [
        {"item_id": "a", "sample_idx": 0, "model": "m", "output_text": "x"},
        {"item_id": "a", "sample_idx": 1, "model": "m", "output_text": "y"},
        {"item_id": "b", "sample_idx": 0, "model": "m", "output_text": "z"},
    ]
    out.write_text("\n".join(json.dumps(r) for r in recs) + "\n")

    assert completed_keys(str(out)) == {("a", 0), ("a", 1), ("b", 0)}
    # missing file -> empty set (no crash)
    assert completed_keys(str(tmp_path / "missing.jsonl")) == set()


# ─────────────────────────────────────────────────────────────────────────────
# run_model — fresh write
# ─────────────────────────────────────────────────────────────────────────────
def test_run_model_writes_all_lines_on_fresh_file(make_client, items, tmp_path):
    subset = items[:5]
    client = make_client(lambda model, messages: "a response")
    out = tmp_path / "m.responses.jsonl"

    counts = run_model({"id": "fake/model"}, subset, client, str(out),
                       samples=3, defaults={"max_tokens": 64})

    assert len(_lines(out)) == len(subset) * 3
    assert counts["written"] == len(subset) * 3
    assert counts["errors"] == 0
    assert counts["skipped"] == 0
    assert len(completed_keys(str(out))) == len(subset) * 3
    # client actually invoked once per (item, sample)
    assert len(client.calls) == len(subset) * 3


def test_run_model_forwards_temperature_and_max_tokens(make_client, items, tmp_path):
    subset = items[:1]
    client = make_client(lambda model, messages: "ok")
    out = tmp_path / "m.responses.jsonl"

    run_model({"id": "fake/model", "temperature": 0.7}, subset, client, str(out),
              samples=1, defaults={"temperature": None, "max_tokens": 128})

    call = client.calls[0]
    assert call["temperature"] == 0.7      # model override wins
    assert call["max_tokens"] == 128       # falls back to defaults


# ─────────────────────────────────────────────────────────────────────────────
# run_model — resume, no duplicates
# ─────────────────────────────────────────────────────────────────────────────
def test_resume_produces_no_duplicate_lines(make_client, items, tmp_path):
    subset = items[:4]
    client = make_client(lambda model, messages: "resp")
    out = tmp_path / "m.responses.jsonl"

    run_model({"id": "fake/model"}, subset, client, str(out), samples=3, defaults={})
    keys_first = completed_keys(str(out))
    n_first = len(_lines(out))

    counts_second = run_model({"id": "fake/model"}, subset, client, str(out),
                              samples=3, defaults={})
    keys_second = completed_keys(str(out))

    assert keys_first == keys_second                       # same key set
    assert n_first == len(_lines(out)) == len(subset) * 3  # no new lines
    assert counts_second["written"] == 0
    assert counts_second["skipped"] == len(subset) * 3


# ─────────────────────────────────────────────────────────────────────────────
# run_model — errors recorded, never dropped
# ─────────────────────────────────────────────────────────────────────────────
def test_error_sample_recorded_not_dropped(make_client, items, tmp_path):
    subset = items[:4]
    target = subset[1]
    target_messages = target.messages()

    def responder(model, messages):
        if messages == target_messages:          # this one item always fails
            raise RuntimeError("boom")
        return "resp"

    client = make_client(responder)
    out = tmp_path / "m.responses.jsonl"

    counts = run_model({"id": "fake/model"}, subset, client, str(out),
                       samples=3, defaults={}, sleep=lambda _d: None)

    records = _records(out)
    assert len(records) == len(subset) * 3       # nothing dropped

    by_item = {}
    for d in records:
        by_item.setdefault(d["item_id"], []).append(d)

    # every sample of the failing item is written with an error
    assert len(by_item[target.id]) == 3
    assert all(d["error"] for d in by_item[target.id])
    assert all(d["output_text"] == "" for d in by_item[target.id])

    # every other item is written cleanly
    for iid, recs in by_item.items():
        if iid != target.id:
            assert all(d["error"] is None for d in recs)

    assert counts["errors"] == 3
    assert counts["written"] == len(subset) * 3

    # resuming still skips the errored lines (they count as recorded)
    counts_resume = run_model({"id": "fake/model"}, subset, client, str(out),
                              samples=3, defaults={}, sleep=lambda _d: None)
    assert counts_resume["written"] == 0
    assert len(_records(out)) == len(subset) * 3


# ─────────────────────────────────────────────────────────────────────────────
# run_all — manifest + per-model files
# ─────────────────────────────────────────────────────────────────────────────
def test_run_all_writes_manifest_and_response_files(make_client, items, tmp_path):
    subset = items[:3]
    client = make_client(lambda model, messages: "resp")
    config = {
        "defaults": {"temperature": None, "max_tokens": 64, "samples": 2},
        "models": [{"id": "fake/model-a", "provider": "Test"}],
        "judge": {"model": "judge-x", "prompt_version": "v1"},
        "seed": 7,
    }

    out = run_all(config, subset, client, str(tmp_path / "results"),
                  started_at="2026-07-09T00:00:00+00:00")

    manifest_path = tmp_path / "results" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["n_items"] == 3
    assert manifest["samples"] == 2
    assert manifest["seed"] == 7
    assert manifest["judge"] == {"model": "judge-x", "prompt_version": "v1"}
    assert manifest["started_at"] == "2026-07-09T00:00:00+00:00"
    assert manifest["models"][0]["id"] == "fake/model-a"
    assert manifest["models"][0]["max_tokens"] == 64

    resp_file = tmp_path / "results" / "raw" / "fake_model-a.responses.jsonl"
    assert resp_file.exists()
    assert len(_lines(resp_file)) == 3 * 2
    assert out["models"]["fake/model-a"]["written"] == 3 * 2


def test_run_all_started_at_falls_back_to_config():
    # library is deterministic: no wall-clock unless caller supplies started_at
    manifest = RunManifest(dataset_version="v2.0.0", n_items=0, models=[], judge={},
                           samples=3)
    assert manifest.started_at is None


# ─────────────────────────────────────────────────────────────────────────────
# main — CLI with an injected fake client (no network)
# ─────────────────────────────────────────────────────────────────────────────
def test_main_writes_manifest_and_lines(make_client, tmp_path):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "defaults:\n"
        "  temperature: null\n"
        "  max_tokens: 64\n"
        "  samples: 2\n"
        "models:\n"
        "  - { id: fake/model-a, provider: Test }\n"
    )
    results = tmp_path / "results"
    client = make_client(lambda model, messages: "resp")

    rc = main(["--config", str(cfg), "--limit", "2", "--results-dir", str(results)],
              client=client)

    assert rc == 0
    manifest_path = results / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["n_items"] == 2
    assert manifest["samples"] == 2
    assert manifest["started_at"]                       # main stamped the clock
    assert manifest["dataset_version"]                  # parsed from CHANGELOG

    resp_files = list((results / "raw").glob("*.responses.jsonl"))
    assert len(resp_files) == 1
    assert len(_lines(resp_files[0])) == 2 * 2          # 2 items * 2 samples

    # every model under test was invoked (no network needed)
    assert len(client.calls) == 2 * 2


def test_main_models_filter_selects_subset(make_client, tmp_path):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "defaults: { temperature: null, max_tokens: 64, samples: 1 }\n"
        "models:\n"
        "  - { id: fake/keep, provider: Test }\n"
        "  - { id: fake/drop, provider: Test }\n"
    )
    results = tmp_path / "results"
    client = make_client(lambda model, messages: "resp")

    main(["--config", str(cfg), "--models", "fake/keep", "--limit", "1",
          "--results-dir", str(results)], client=client)

    resp_files = {p.name for p in (results / "raw").glob("*.responses.jsonl")}
    assert resp_files == {"fake_keep.responses.jsonl"}
    manifest = json.loads((results / "manifest.json").read_text())
    assert [m["id"] for m in manifest["models"]] == ["fake/keep"]
