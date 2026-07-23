"""Gaslighting Index v2 — misinformation-persistence benchmark harness.

Public surface is intentionally small; import submodules directly:

    from gaslight.data import load_items
    from gaslight.score import classify, aggregate
    from gaslight import stats

See docs/CONTRACT.md for the interface + scoring contract every module honors.
"""

__version__ = "2.0.0"
