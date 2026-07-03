"""SEC-16 drift guard: every CSV export site must route rows through
``escape_csv_row`` (CSV / spreadsheet-formula injection defense).

Data is stored verbatim (correct — neutralizing on import would corrupt
legitimate values like negative numbers), so the escaping has to happen at
CSV-write time. Today every export uses ``apps.shared.csv_safety.escape_csv_row``;
this test fails the build if a NEW export module writes CSV rows without it,
instead of letting the gap ship silently.
"""

from __future__ import annotations

from pathlib import Path

APPS_DIR = Path(__file__).resolve().parents[3]


def test_csv_export_sites_route_through_escape_csv_row() -> None:
    files_with_writerow: list[str] = []
    offenders: list[str] = []

    for path in APPS_DIR.rglob("*.py"):
        parts = path.parts
        if "tests" in parts or "migrations" in parts:
            continue
        text = path.read_text()
        if "writerow" not in text:
            continue
        rel = str(path.relative_to(APPS_DIR.parent))
        files_with_writerow.append(rel)
        if "escape_csv_row" not in text:
            offenders.append(rel)

    # Non-vacuity guard: if the scan finds nothing (mis-pathed), don't pass
    # trivially — there are known export sites (shares_viewsets,
    # documentation_export_service).
    assert files_with_writerow, (
        "No CSV-writing modules found — the scan is mis-pathed "
        f"(APPS_DIR={APPS_DIR}). This guard must not pass on an empty set."
    )
    assert not offenders, (
        "CSV export site(s) write rows without escape_csv_row "
        "(apps.shared.csv_safety) — spreadsheet-formula injection risk:\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\nWrap row data in escape_csv_row(...) before writer.writerow(...)."
    )
