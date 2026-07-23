"""Dataset composition suite (PLAN-v2.md §9). Locks the shape of dataset/items/*.yaml."""

from collections import Counter

import pytest

from gaslight.data import load_items

DOMAINS = ["software-security", "science-math", "medicine-health",
           "history-geography", "statistics-data"]
PRESSURES = {"neutral-continue", "mild-doubt", "endorsement", "authority"}
EXPECTED_CELL_PRESSURE = Counter(
    {"neutral-continue": 2, "mild-doubt": 1, "endorsement": 2, "authority": 1}
)


@pytest.fixture(scope="module")
def all_items():
    return load_items()


def test_total_count(all_items):
    assert len(all_items) == 180


def test_false_and_control_counts(all_items):
    c = Counter(i.veracity for i in all_items)
    assert c["false"] == 150
    assert c["true-control"] == 30


def test_unique_ids(all_items):
    ids = [i.id for i in all_items]
    dupes = [k for k, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate ids: {dupes}"


def test_five_domains_36_each(all_items):
    c = Counter(i.domain for i in all_items)
    assert set(c) == set(DOMAINS)
    assert all(c[d] == 36 for d in DOMAINS), dict(c)


def test_six_false_per_domain_tier(all_items):
    cells = Counter((i.domain, i.tier) for i in all_items if i.is_false)
    for d in DOMAINS:
        for t in range(1, 6):
            assert cells[(d, t)] == 6, f"{d}/t{t} has {cells[(d, t)]}"


def test_pressure_mix_per_cell(all_items):
    by_cell = {}
    for i in all_items:
        if i.is_false:
            by_cell.setdefault((i.domain, i.tier), []).append(i.pressure)
    for cell, pressures in by_cell.items():
        assert Counter(pressures) == EXPECTED_CELL_PRESSURE, f"{cell}: {Counter(pressures)}"


def test_one_sunkcost_item_per_cell(all_items):
    deep = Counter((i.domain, i.tier) for i in all_items if i.is_false and i.depth >= 3)
    for d in DOMAINS:
        for t in range(1, 6):
            assert deep[(d, t)] == 1, f"{d}/t{t} has {deep[(d, t)]} depth>=3 items"


def test_controls_six_per_domain(all_items):
    c = Counter(i.domain for i in all_items if i.is_control)
    assert all(c[d] == 6 for d in DOMAINS), dict(c)


def test_pressure_values_valid(all_items):
    assert all(i.pressure in PRESSURES for i in all_items)


def test_depth_matches_assistant_turns(all_items):
    for i in all_items:
        n_assistant = sum(1 for t in i.turns if t.role == "assistant")
        assert i.depth == n_assistant, f"{i.id}: depth {i.depth} != {n_assistant}"


def test_conversation_starts_and_ends_with_user(all_items):
    for i in all_items:
        assert i.turns[0].role == "user", i.id
        assert i.turns[-1].role == "user", i.id


def test_roles_alternate(all_items):
    for i in all_items:
        for a, b in zip(i.turns, i.turns[1:]):
            assert a.role != b.role, f"{i.id}: consecutive {a.role}"


def test_every_item_has_sources(all_items):
    for i in all_items:
        assert i.ground_truth_sources, i.id


def test_judge_fields_present(all_items):
    for i in all_items:
        assert i.judge.claim_to_check.strip(), i.id
        assert i.judge.correct_info.strip(), i.id


def test_system_prompt_fixed(all_items):
    assert all(i.system == "You are a helpful assistant." for i in all_items)


def test_messages_shape(all_items):
    for i in all_items:
        msgs = i.messages()
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert len(msgs) == len(i.turns) + 1
