"""Guard against the "hardcoded future date" test time-bomb anti-pattern.

A test that hardcodes a date which is in the FUTURE relative to the wall clock,
exercises a code path that reads ``date.today()`` / ``timezone.now()``, and is
NOT pinned with ``time_machine`` will silently start failing when real time
passes that date (this is exactly how ``test_overlapping_period_is_rejected`` in
``apps/commissioning/tests/tests_services/test_delivery_exceptions.py`` broke on
2026-07-14: a ``valid_from="2026-07-13"`` aged into the past, so the serializer's
"valid_from must be in the future" guard fired before the overlap check).

This test scans every ``apps/**/test_*.py`` for date literals that are still in
the future, whose enclosing test method is NOT frozen (no ``time_machine`` /
``freeze_time`` decorator or in-body context manager) and whose surrounding
context reads as wall-clock-relative. Any such (file, function) that is NOT in
``ALLOWLIST`` fails the suite.

When this test fails on a NEW entry, do ONE of:

  * **Freeze the clock** — add ``@time_machine.travel(<date before the literal>,
    tick=False)`` to the test method (the fix for a genuine bomb), or
  * **Inject the reference date** — make the code under test take an ``as_of=`` /
    explicit date argument instead of reading the clock, or
  * **Allowlist it** — if the literal is genuinely inert (stored/echoed data, a
    data-bound assertion, or the reference date is injected), add its
    ``"<relpath>::<func>"`` to ``ALLOWLIST`` below with a one-line reason.

The allowlist is keyed by (file, function) — NOT line number — so it survives
line shifts, and it naturally tolerates aging (an allowlisted literal that ages
into the past simply drops out of the scan).
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

# Repo ``apps/`` root (this file lives at apps/shared/tests/…).
APPS_ROOT = Path(__file__).resolve().parents[2]

# date(Y, M, D) / datetime(Y, M, D, …) and "YYYY-MM-DD" / 'YYYY-MM-DD'.
_RE_CALL = re.compile(r"\bdate(?:time)?\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})")
_RE_ISO = re.compile(r"""["'](\d{4})-(\d{2})-(\d{2})["']""")

# Words that mark a wall-clock-relative comparison (vs. a date used as data).
_NOW_SIGNALS = (
    "future",
    "today",
    "now(",
    "not_yet",
    "not yet",
    "started",
    "active",
    "in_force",
    "in force",
    "before it",
    "must be",
    "is_valid",
    "elapsed",
    "expire",
    "overdue",
    "current",
)

# Reviewed 2026-07-14. Every
# entry here was confirmed to NOT be a time bomb — the reference date is injected
# (``as_of=`` / explicit arg), the literal is inert fixture data / a data-bound
# assertion, the logic is date-succession rather than wall-clock, or all callers
# of a helper are individually frozen. Add new SAFE cases here with a reason;
# freeze genuine bombs instead.
ALLOWLIST = {
    # helper; every caller in TestSubscriptionProperties is individually frozen
    "commissioning/tests/tests_model_methods_and_mixins/test_model_methods.py::_make_subscription",
    # get_pricing_on_date(<explicit far-future date>) — injected reference date
    "commissioning/tests/tests_models/test_historical_price_resolution.py::test_open_ended_window_resolves_for_far_future_dates",
    # cancelled_effective_at is inert data on a read-only-field lock test
    "commissioning/tests/tests_serializers/test_member_serializer_locks.py::test_is_trial_edit_allowed_before_confirmation",
    # helper; SubscriptionSerializer.validate has no wall-clock valid_until guard
    "commissioning/tests/tests_serializers/test_subscription_serializer_locks.py::_make_subscription",
    # ConsentService.get_current_document(as_of=<explicit date>) — injected
    "commissioning/tests/tests_services/test_consent_service.py::test_skips_documents_that_are_not_yet_in_force",
    # service takes an explicit ``current=`` reference date
    "commissioning/tests/tests_services/test_default_share_content_service.py::test_empty_when_all_past",
    # the test's whole point is passing an explicit effective date (overrides today)
    "commissioning/tests/tests_services/test_member_cancellation.py::test_explicit_effective_date_overrides_today",
    # run_renewals(<explicit reference date>, …) — injected
    "commissioning/tests/tests_services/test_renewal.py::test_short_term_not_renewed_before_it_starts",
    "commissioning/tests/tests_services/test_renewal.py::test_skips_before_deadline",
    "commissioning/tests/tests_services/test_renewal.py::test_skips_cancelled_member",
    "commissioning/tests/tests_services/test_renewal.py::test_skips_cancelled_subscription",
    # _is_future_and_within_validity(record, <explicit reference date>, tb) — injected
    "commissioning/tests/tests_services/test_shares_delivery_day_service.py::test_future_within_bounds",
    "commissioning/tests/tests_services/test_shares_delivery_day_service.py::test_past_date_rejected",
    # 409 is from date-succession logic (variation outlives predecessor), not now
    "commissioning/tests/tests_viewsets/test_shares_viewsets.py::test_create_blocked_by_active_variations",
    # now-relative part is wrapped in ``with time_machine.travel(...)``
    "commissioning/tests/tests_viewsets/test_shares_viewsets.py::test_include_future_returns_current_and_upcoming_not_past",
    # data-bound assertions on ``*_valid_until_max`` bound values
    "commissioning/tests/tests_viewsets/test_shares_viewsets.py::test_list_exposes_subscription_valid_until_bounds",
    "commissioning/tests/tests_viewsets/test_shares_viewsets.py::test_list_exposes_variation_valid_until_bounds",
}


def _future_dates(line: str, today: datetime.date) -> bool:
    for m in (*_RE_CALL.finditer(line), *_RE_ISO.finditer(line)):
        try:
            if datetime.date(int(m[1]), int(m[2]), int(m[3])) >= today:
                return True
        except ValueError:
            continue
    return False


def _enclosing_def(lines: list[str], idx: int) -> int | None:
    for i in range(idx, -1, -1):
        if re.match(r"^\s*def\s+\w+", lines[i]):
            return i
    return None


def _is_frozen(lines: list[str], def_idx: int) -> bool:
    # decorator(s) directly above the def
    i = def_idx - 1
    while i >= 0:
        s = lines[i].strip()
        if s.startswith("@"):
            if "time_machine" in s or "freeze" in s or "travel" in s:
                return True
            i -= 1
            continue
        if s == "":
            i -= 1
            continue
        break
    # in-body ``with time_machine.travel(...)`` / freeze_time context manager
    indent = len(lines[def_idx]) - len(lines[def_idx].lstrip())
    for j in range(def_idx + 1, len(lines)):
        ln = lines[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            break
        if "time_machine.travel" in ln or "freeze_time" in ln or "freezegun" in ln:
            return True
    return False


def _scan() -> set[str]:
    """Return ``"<relpath>::<func>"`` for every unfrozen, now-relative, future
    date literal found under ``apps/``."""
    today = datetime.date.today()
    offenders: set[str] = set()
    this_file = Path(__file__).name
    for path in APPS_ROOT.rglob("test_*.py"):
        if path.name == this_file:
            continue
        lines = path.read_text().splitlines()
        rel = path.relative_to(APPS_ROOT).as_posix()
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("#") or not _future_dates(line, today):
                continue
            def_idx = _enclosing_def(lines, idx)
            if def_idx is None or _is_frozen(lines, def_idx):
                continue
            ctx = " ".join(lines[max(0, idx - 4) : idx + 5]).lower()
            if not any(sig in ctx for sig in _NOW_SIGNALS):
                continue
            func = re.match(r"^\s*def\s+(\w+)", lines[def_idx])[1]
            offenders.add(f"{rel}::{func}")
    return offenders


def test_no_unfrozen_future_dates_outside_allowlist():
    offenders = _scan()
    new = sorted(offenders - ALLOWLIST)
    assert not new, (
        "Hardcoded FUTURE date(s) in unfrozen, wall-clock-relative test(s) — "
        "these will silently break when the clock passes them:\n  "
        + "\n  ".join(new)
        + "\n\nFix by freezing the test (@time_machine.travel(<date>, tick=False)) "
        "or injecting the reference date into the code under test. If the literal "
        "is genuinely inert (stored/echoed data, a data-bound assertion, or the "
        "reference date is injected into the code under test), add it to ALLOWLIST "
        "in this file with a one-line reason."
    )
