"""Dataset loading. Single source of truth = dataset/items/*.yaml."""

from __future__ import annotations

import glob
import os

import yaml

from .types import Item, JudgeSpec, Turn

_HERE = os.path.dirname(os.path.abspath(__file__))
# repo_root/src/gaslight/data.py -> repo_root
REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
DEFAULT_ITEMS_DIR = os.path.join(REPO_ROOT, "dataset", "items")


def _parse_item(raw: dict) -> Item:
    conv = raw["conversation"]
    turns = [Turn(role=t["role"], content=t["content"]) for t in conv["turns"]]
    j = raw["judge"]
    veracity = raw["veracity"]
    if isinstance(veracity, bool):  # defensive: unquoted YAML `false`
        veracity = "false"
    return Item(
        id=raw["id"],
        version=int(raw["version"]),
        domain=raw["domain"],
        tier=int(raw["tier"]),
        veracity=veracity,
        pressure=raw["pressure"],
        depth=int(raw["depth"]),
        claim=raw["claim"],
        ground_truth=raw["ground_truth"],
        ground_truth_sources=list(raw["ground_truth_sources"]),
        system=conv["system"],
        turns=turns,
        judge=JudgeSpec(claim_to_check=j["claim_to_check"], correct_info=j["correct_info"]),
        notes=raw.get("notes", ""),
        probe_type=raw.get("probe_type", "open-propagation"),
        source_status=raw.get("source_status", ""),
        source_locator=raw.get("source_locator", ""),
        source_error=raw.get("source_error", ""),
        temporal_scope=raw.get("temporal_scope", ""),
        review_after=raw.get("review_after", ""),
        claim_overlap_verified=bool(raw.get("claim_overlap_verified", False)),
    )


def load_items(items_dir: str | None = None) -> list[Item]:
    """Load and return all dataset items, sorted by id. Raises on duplicate ids."""
    items_dir = items_dir or DEFAULT_ITEMS_DIR
    files = sorted(glob.glob(os.path.join(items_dir, "*.yaml")))
    if not files:
        raise FileNotFoundError(f"No dataset item files in {items_dir}")
    items: list[Item] = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            raw_list = yaml.safe_load(fh)
        if not isinstance(raw_list, list):
            raise ValueError(f"{f}: top level must be a list of items")
        for raw in raw_list:
            items.append(_parse_item(raw))
    seen: dict[str, str] = {}
    for it in items:
        if it.id in seen:
            raise ValueError(f"Duplicate item id: {it.id}")
        seen[it.id] = it.id
    items.sort(key=lambda it: it.id)
    return items


def index_by_id(items: list[Item]) -> dict[str, Item]:
    return {it.id: it for it in items}
