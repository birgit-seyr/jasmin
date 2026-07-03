"""Drift guard for the ShareDelivery ship predicate.

"Does this delivery count?" has exactly one answer —
``ShareDelivery.delivery_counts_q()`` (joker not taken AND not opted out),
surfaced as the ``ShareDelivery.objects.shippable()`` queryset. A new
aggregation that sums ``subscription__quantity`` over ShareDelivery rows
WITHOUT routing through the predicate silently over-counts (jokered/opted-out
rows shipped on a pickup sheet — the historical API-1 failure). This test
AST-scans the app tree: every function that both touches ShareDelivery rows
and reads ``subscription__quantity`` must reference one of the predicate
helpers, or be explicitly allow-listed with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

DJANGO_CORE = Path(__file__).resolve().parents[4]
APPS = DJANGO_CORE / "apps"
IGNORED_APPS = frozenset({"cultivation", "economics", "staff"})

_PREDICATE_TOKENS = ("shippable(", "delivery_counts_q(", "opted_out_q(")

# (module-relative-path, function name) → why the raw aggregation is correct
# WITHOUT the ship predicate. Keep this list short and justified.
_ALLOWED_RAW_AGGREGATIONS: dict[tuple[str, str], str] = {}


def _function_spans(tree: ast.Module, source: str) -> list[tuple[str, str]]:
    """(name, source_segment) for every function/method in the module."""
    spans: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(source, node) or ""
            spans.append((node.name, segment))
    return spans


def test_share_delivery_quantity_aggregations_use_ship_predicate() -> None:
    offenders: list[str] = []
    scanned = 0
    for path in sorted(APPS.rglob("*.py")):
        parts = path.relative_to(APPS).parts
        if parts[0] in IGNORED_APPS or "tests" in parts or "migrations" in parts:
            continue
        source = path.read_text()
        if "subscription__quantity" not in source:
            continue
        tree = ast.parse(source)
        relative = str(path.relative_to(APPS))
        for name, segment in _function_spans(tree, source):
            if "subscription__quantity" not in segment:
                continue
            # Only SUM-aggregations directly over ShareDelivery rows are in
            # scope: a per-row ``F("subscription__quantity")`` display
            # annotation is not a count, and a Sum over another model (e.g.
            # CapacityReservation — pre-confirm holds with no joker/opt-in
            # state) has its own semantics.
            if "ShareDelivery.objects" not in segment or "Sum(" not in segment:
                continue
            scanned += 1
            if any(token in segment for token in _PREDICATE_TOKENS):
                continue
            if (relative, name) in _ALLOWED_RAW_AGGREGATIONS:
                continue
            offenders.append(f"{relative}::{name}")

    # Non-vacuity: the scan must find the known-correct call sites, or the
    # heuristics are broken and the guard is asserting nothing.
    assert scanned >= 3, (
        f"Ship-predicate scan only matched {scanned} function(s) — the "
        "detection heuristics are broken; this guard must not pass vacuously."
    )
    assert not offenders, (
        "ShareDelivery quantity aggregation(s) without the ship predicate "
        "(route through ShareDelivery.objects.shippable() / "
        "delivery_counts_q(), or allow-list with a reason):\n"
        + "\n".join(f"  - {offender}" for offender in offenders)
    )
