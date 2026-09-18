"""Guard against the "hardcoded future date" test time-bomb anti-pattern.

A test that hardcodes a date which is in the FUTURE relative to the wall clock,
exercises a code path that reads ``date.today()`` / ``timezone.now()``, and is
NOT pinned with ``time_machine`` will silently start failing when real time
passes that date (e.g. a ``valid_from`` literal ages into the past, so a
"valid_from must be in the future" guard fires before the check under test).

This test scans every ``apps/**/test_*.py`` for date literals that are still in
the future, whose enclosing scope is NOT frozen (no ``time_machine`` /
``freeze_time`` decorator, in-body context manager, or class- or module-scoped
autouse fixture) and whose surrounding context reads as wall-clock-relative. Any
such (file, scope) that is NOT in ``ALLOWLIST`` fails the suite.

A literal's scope comes from the parsed syntax tree, not from its position in
the file: it belongs to the innermost ``def`` whose decorators, header or body
span it, else to the innermost enclosing ``class``, else to the module. So a
``@pytest.mark.parametrize`` date is the decorated test's data, and a shared
constant keeps module scope wherever in the file it sits — below a helper
``def`` as readily as above it.

A literal at MODULE scope — a shared ``_SPAN`` / ``_VALID_UNTIL`` constant — is
judged differently, because the per-function test does not apply to it: it has
no enclosing ``def``, so it carries no decorator and no autouse fixture of its
own, and it reaches the clock only through whichever tests spread it. Its
neighbouring lines are its own definition block, so the wall-clock-relative
wording that identifies a per-function literal says nothing about it. What
decides it is the module: such a constant is dangerous exactly when some test in
the file runs against the real clock, since a frozen test cannot observe real
time at all and the constant's futureness then holds forever. So a module-level
future literal is reported — keyed ``"<relpath>::<module>"`` — when at least one
test in the file is unfrozen, and is silent when every test is frozen. Which of
the file's tests actually spread the constant into now-relative code is a
judgement a reader makes once per module and records in ``ALLOWLIST``.

A literal in a CLASS BODY is the same shape one level down: it reaches only that
class's tests, so it is reported — keyed ``"<relpath>::<ClassName>"`` — when a
test in the class is unfrozen, and is silent when the class is frozen whole (a
``time_machine`` class decorator, a class-scoped ``autouse`` fixture, or a
module-wide freeze).

When this test fails on a NEW entry, do ONE of:

  * **Freeze the clock** — put the test under ``time_machine.travel(<date before
    the literal>, tick=False)`` (the fix for a genuine bomb), as a decorator on
    the method or, for a whole plain-pytest class, an autouse fixture. A
    ``"::<module>"`` entry clears once EVERY test in the file is frozen, which a
    module-level ``autouse`` fixture does in one place, or
  * **Inject the reference date** — make the code under test take an ``as_of=`` /
    explicit date argument instead of reading the clock, or
  * **Allowlist it** — if the literal is genuinely inert (stored/echoed data, a
    data-bound assertion, or the reference date is injected), add its
    ``"<relpath>::<func>"`` to ``ALLOWLIST`` below with a one-line reason.

The allowlist is keyed by (file, scope) — NOT line number — so it survives line
shifts, and it naturally tolerates aging (an allowlisted literal that ages into
the past simply drops out of the scan).
"""

from __future__ import annotations

import ast
import datetime
import re
from pathlib import Path
from textwrap import dedent

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

# A decorator pinning the clock: ``@time_machine.travel(…)``, ``@freeze_time(…)``.
_DECORATOR_FREEZE_MARKERS = ("time_machine", "freeze", "travel")
# The same pin as a statement — a ``with`` block or a fixture's context manager.
_BODY_FREEZE_MARKERS = ("time_machine.travel", "freeze_time", "freezegun")

_FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)

# The scope part of a module-scope entry: no ``def`` and no ``class`` encloses
# the literal, so the whole file is the unit being allowed.
MODULE_SCOPE_KEY = "<module>"

# Every entry here was confirmed to NOT be a time bomb — the reference date is injected
# (``as_of=`` / explicit arg), the literal is inert fixture data / a data-bound
# assertion, the logic is date-succession rather than wall-clock, or all callers
# of a helper are individually frozen. Add new SAFE cases here with a reason;
# freeze genuine bombs instead.
ALLOWLIST = {
    # every date is an explicit argument; the policy service reads no clock
    "commissioning/tests/tests_services/test_additional_share_policy.py::<module>",
    # run_renewals(<explicit reference date>) — the module's dates never meet the clock
    "commissioning/tests/tests_services/test_renewal.py::<module>",
    # helper; every caller in TestSubscriptionProperties is individually frozen
    "commissioning/tests/tests_model_methods_and_mixins/test_model_methods.py::_make_subscription",
    # cancelled_effective_at is inert parametrize data on a read-only-field lock test
    "commissioning/tests/tests_serializers/test_member_serializer_locks.py::test_field_is_silently_dropped_from_payload",
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
}


def _future_dates(line: str, today: datetime.date) -> bool:
    for m in (*_RE_CALL.finditer(line), *_RE_ISO.finditer(line)):
        try:
            if datetime.date(int(m[1]), int(m[2]), int(m[3])) >= today:
                return True
        except ValueError:
            continue
    return False


def _compact(text: str) -> str:
    """Drop every space and newline, so a wrapped call reads like a one-liner."""
    return "".join(text.split())


class _ScannedModule:
    """One test module, indexed by the scope each source line belongs to.

    Scope is structural: the innermost ``def``/``class`` whose span covers the
    line, decorators included. That keeps a module constant at module scope
    wherever it sits in the file, and attributes a decorator argument to the
    definition it decorates rather than to whatever happens to precede it.
    """

    def __init__(self, source: str) -> None:
        self.lines = source.splitlines()
        self._function_at: dict[int, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self._class_at: dict[int, ast.ClassDef] = {}
        self._owner_class: dict[str, ast.ClassDef] = {}
        self._tree = ast.parse(source)
        self._index(self._tree, None)
        self.module_frozen = any(
            self._is_autouse_fixture(node) and self._body_freezes(node)
            for node in self._tree.body
            if isinstance(node, _FUNCTION_TYPES)
        )
        self._class_frozen: dict[str, bool] = {}
        self._module_exposed: bool | None = None

    # -- indexing ---------------------------------------------------------

    def _index(self, node: ast.AST, enclosing: ast.ClassDef | None) -> None:
        """Map every line to its innermost definition, parents first."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNCTION_TYPES):
                start, end = _span(child)
                for lineno in range(start, end + 1):
                    self._function_at[lineno] = child
                if enclosing is not None:
                    self._owner_class[_key(child)] = enclosing
                self._index(child, enclosing)
            elif isinstance(child, ast.ClassDef):
                start, end = _span(child)
                for lineno in range(start, end + 1):
                    self._class_at[lineno] = child
                self._index(child, child)
            else:
                self._index(child, enclosing)

    # -- freeze detection -------------------------------------------------

    def _segment(self, node: ast.AST) -> str:
        start, end = _span(node)
        return "\n".join(self.lines[start - 1 : end])

    def _is_autouse_fixture(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any(
            "autouse=True" in _compact(self._segment(d)) for d in node.decorator_list
        )

    def _decorators_freeze(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> bool:
        # Matched against the decorator's NAME, never its source span: the
        # markers are ordinary words that also occur in a ``mock.patch`` target
        # or a parametrize id, and a span match would let one of those silence
        # the whole def — or, on a class decorator, every test in the class.
        return any(
            any(
                marker in _decorator_name(decorator)
                for marker in _DECORATOR_FREEZE_MARKERS
            )
            for decorator in node.decorator_list
        )

    def _body_freezes(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """True if the ``def`` pins the clock somewhere in its body."""
        end = node.end_lineno or node.lineno
        body = "\n".join(self.lines[node.lineno : end])
        return any(marker in body for marker in _BODY_FREEZE_MARKERS)

    def class_frozen(self, node: ast.ClassDef) -> bool:
        """True if the class pins the clock for every test it holds.

        Either a ``time_machine`` class decorator (which applies to a
        ``unittest.TestCase``) or an ``autouse`` fixture wrapping the clock
        (the plain-pytest equivalent, and the only shape that works there).
        """
        cached = self._class_frozen.get(_key(node))
        if cached is None:
            cached = self._decorators_freeze(node) or any(
                self._is_autouse_fixture(m) and self._body_freezes(m)
                for m in node.body
                if isinstance(m, _FUNCTION_TYPES)
            )
            self._class_frozen[_key(node)] = cached
        return cached

    def function_frozen(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        if (
            self.module_frozen
            or self._decorators_freeze(node)
            or self._body_freezes(node)
        ):
            return True
        owner = self._owner_class.get(_key(node))
        return owner is not None and self.class_frozen(owner)

    # -- exposure ---------------------------------------------------------

    def _unfrozen_test_in(self, node: ast.AST) -> bool:
        return any(
            child.name.startswith("test_") and not self.function_frozen(child)
            for child in ast.walk(node)
            if isinstance(child, _FUNCTION_TYPES)
        )

    def module_exposed(self) -> bool:
        """True if any test in the file runs against the real clock."""
        if self._module_exposed is None:
            self._module_exposed = not self.module_frozen and self._unfrozen_test_in(
                self._tree
            )
        return self._module_exposed

    def class_exposed(self, node: ast.ClassDef) -> bool:
        if self.module_frozen or self.class_frozen(node):
            return False
        return self._unfrozen_test_in(node)

    def _now_relative(self, idx: int) -> bool:
        context = " ".join(self.lines[max(0, idx - 4) : idx + 5]).lower()
        return any(signal in context for signal in _NOW_SIGNALS)

    # -- the verdict ------------------------------------------------------

    def offender_scope(self, idx: int) -> str | None:
        """Scope key to report the literal on line ``idx`` under, None if silent."""
        lineno = idx + 1
        function = self._function_at.get(lineno)
        if function is not None:
            if self.function_frozen(function) or not self._now_relative(idx):
                return None
            return function.name
        holder = self._class_at.get(lineno)
        if holder is not None:
            return holder.name if self.class_exposed(holder) else None
        return MODULE_SCOPE_KEY if self.module_exposed() else None


def _decorator_name(node: ast.AST) -> str:
    """The decorator's dotted name, with its arguments left out.

    ``@time_machine.travel(...)`` yields ``time_machine.travel`` whether or not
    the call wraps across lines, so the freeze markers match the decorator that
    was applied rather than anything it was passed.
    """
    if isinstance(node, ast.Call):
        node = node.func
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _key(node: ast.AST) -> str:
    """Identity of a definition node — its exact source span."""
    start, end = _span(node)
    return f"{start}:{end}"


def _span(node: ast.AST) -> tuple[int, int]:
    """1-based inclusive line span of a definition, decorators included."""
    start: int = getattr(node, "lineno", 1)
    end: int = getattr(node, "end_lineno", None) or start
    for decorator in getattr(node, "decorator_list", []):
        start = min(start, decorator.lineno)
    return start, end


def _scan(root: Path = APPS_ROOT) -> set[str]:
    """Return ``"<relpath>::<scope>"`` for every unfrozen, now-relative, future
    date literal found under ``root``, plus ``"<relpath>::<module>"`` /
    ``"<relpath>::<ClassName>"`` for a shared literal whose module or class
    still has an unfrozen test."""
    today = datetime.date.today()
    offenders: set[str] = set()
    this_file = Path(__file__).name
    for path in sorted(root.rglob("test_*.py")):
        if path.name == this_file:
            continue
        source = path.read_text()
        # Parsing is the expensive half, so only files that actually hold a
        # future literal pay for it.
        candidates = [
            idx
            for idx, line in enumerate(source.splitlines())
            if not line.lstrip().startswith("#") and _future_dates(line, today)
        ]
        if not candidates:
            continue
        try:
            module = _ScannedModule(source)
        except SyntaxError:
            # A file that does not parse cannot run as a test either, so pytest
            # already fails loudly on it. Crashing here as well would bury that
            # failure under a traceback from an unrelated test.
            continue
        rel = path.relative_to(root).as_posix()
        for idx in candidates:
            scope = module.offender_scope(idx)
            if scope is not None:
                offenders.add(f"{rel}::{scope}")
    return offenders


def test_no_unfrozen_future_dates_outside_allowlist():
    offenders = _scan()
    new = sorted(offenders - ALLOWLIST)
    assert not new, (
        "Hardcoded FUTURE date(s) in unfrozen, wall-clock-relative test(s) — "
        "these will silently break when the clock passes them:\n  "
        + "\n  ".join(new)
        + "\n\nFix by freezing the test (@time_machine.travel(<date>, tick=False)) "
        "or injecting the reference date into the code under test. An entry ending "
        "in '::<module>' is a module-level date constant shared by the whole file; "
        "it clears once every test in that file is frozen, which a module-level "
        "autouse fixture does in one place. An entry ending in a class name is the "
        "same thing one level down — a constant in a class body, cleared by "
        "freezing that class. If the literal is genuinely inert (stored/echoed "
        "data, a data-bound assertion, or the reference date is injected into the "
        "code under test), add it to ALLOWLIST in this file with a one-line reason."
    )


# ---------------------------------------------------------------------------
# The detector itself. Each case writes a synthetic module into ``tmp_path``
# and scans that directory, so the assertions are about the scanner and not
# about whatever the repo happens to contain today.
# ---------------------------------------------------------------------------

# Relative to the clock, so the fixture data stays future-dated forever.
_FUTURE = datetime.date.today() + datetime.timedelta(days=365)
_FUTURE_DATE = f"datetime.date({_FUTURE.year}, {_FUTURE.month}, {_FUTURE.day})"


def _scan_source(tmp_path: Path, source: str) -> set[str]:
    """Scan one synthetic module; ``FUTURE_DATE`` stands in for a future literal."""
    body = dedent(source).replace("FUTURE_DATE", _FUTURE_DATE)
    (tmp_path / "test_sample.py").write_text(body)
    return _scan(tmp_path)


def test_module_constant_above_the_first_def_is_reported(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        _VALID_UNTIL = FUTURE_DATE


        def test_subscription_is_current():
            assert _VALID_UNTIL
        """,
    )
    assert offenders == {"test_sample.py::<module>"}


def test_module_constant_below_a_def_is_still_reported(tmp_path):
    """Scope is structural, so a constant does not become a helper's local by
    sitting underneath it."""
    offenders = _scan_source(
        tmp_path,
        """
        import datetime


        def _make_subscription():
            return None


        _VALID_UNTIL = FUTURE_DATE


        def test_subscription_is_current():
            assert _VALID_UNTIL
        """,
    )
    assert offenders == {"test_sample.py::<module>"}


def test_module_autouse_freeze_silences_the_constant(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import pytest
        import time_machine

        _VALID_UNTIL = FUTURE_DATE


        @pytest.fixture(autouse=True)
        def _frozen_clock():
            with time_machine.travel(datetime.datetime(2020, 1, 6, 12, 0), tick=False):
                yield


        def test_subscription_is_current():
            assert _VALID_UNTIL
        """,
    )
    assert offenders == set()


def test_multiline_autouse_freeze_silences_the_whole_module(tmp_path):
    """An ``autouse`` fixture whose arguments wrap across lines still freezes
    every test in the file.

    The literal sits inside the test, in a now-relative context, so it is
    reported unless that fixture is recognised — which is what makes this a
    regression test rather than a restatement of the scope rules.
    """
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import pytest
        import time_machine


        @pytest.fixture(
            autouse=True,
            name="_frozen_clock",
        )
        def _frozen_clock():
            with time_machine.travel(datetime.datetime(2020, 1, 6, 12, 0), tick=False):
                yield


        def test_subscription_is_current():
            # the term must still be in the future when the guard runs
            assert FUTURE_DATE
        """,
    )
    assert offenders == set()


def test_class_body_constant_is_reported_against_its_class(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime


        class TestSubscriptionWindow:
            valid_until = FUTURE_DATE

            def test_is_current(self):
                assert self.valid_until
        """,
    )
    assert offenders == {"test_sample.py::TestSubscriptionWindow"}


def test_class_decorator_freeze_silences_its_tests(tmp_path):
    """A ``time_machine`` decorator on the CLASS freezes every test it holds —
    the shape a ``unittest.TestCase`` uses.

    As above, the literal is inside a test and in a now-relative context, so
    only recognising the class decorator keeps it silent.
    """
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import time_machine


        @time_machine.travel("2020-01-06", tick=False)
        class TestSubscriptionWindow:
            def test_is_current(self):
                # the term must still be in the future when the guard runs
                assert FUTURE_DATE
        """,
    )
    assert offenders == set()


def test_class_autouse_freeze_silences_a_class_body_constant(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import pytest
        import time_machine


        class TestSubscriptionWindow:
            valid_until = FUTURE_DATE

            @pytest.fixture(autouse=True)
            def _frozen_clock(self):
                with time_machine.travel(datetime.datetime(2020, 1, 6), tick=False):
                    yield

            def test_is_current(self):
                assert self.valid_until
        """,
    )
    assert offenders == set()


def test_in_body_freeze_below_a_wrapped_signature_is_seen(tmp_path):
    """The body searched for the clock pin is the whole body — a ``def`` whose
    arguments wrap across lines does not cut it short at the closing paren."""
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import time_machine


        def test_include_future_returns_upcoming(
            api_client,
            tenant,
        ):
            with time_machine.travel(datetime.date(2020, 1, 6)):
                # the upcoming term must still be in the future here
                assert FUTURE_DATE
        """,
    )
    assert offenders == set()


def test_async_test_keeps_a_module_constant_exposed(tmp_path):
    """An ``async def`` test reads the same wall clock as a plain one."""
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        _VALID_UNTIL = FUTURE_DATE


        async def test_subscription_is_current():
            assert _VALID_UNTIL
        """,
    )
    assert offenders == {"test_sample.py::<module>"}


def test_literal_in_an_unfrozen_test_is_reported(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime


        def test_subscription_is_current():
            # the term must be in the future for the guard to pass
            assert FUTURE_DATE
        """,
    )
    assert offenders == {"test_sample.py::test_subscription_is_current"}


def test_literal_in_a_frozen_test_is_silent(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import time_machine


        @time_machine.travel(datetime.datetime(2020, 1, 6, 12, 0), tick=False)
        def test_subscription_is_current():
            # the term must be in the future for the guard to pass
            assert FUTURE_DATE
        """,
    )
    assert offenders == set()


def test_parametrize_literal_belongs_to_the_decorated_test(tmp_path):
    """A decorator argument is the decorated test's data, not the preceding
    function's."""
    offenders = _scan_source(
        tmp_path,
        """
        import datetime

        import pytest


        def test_unrelated():
            assert True


        @pytest.mark.parametrize(
            "field,value",
            [
                # the guard rejects a term that is not yet active
                ("cancelled_effective_at", FUTURE_DATE),
            ],
        )
        def test_field_is_dropped(field, value):
            assert field
        """,
    )
    assert offenders == {"test_sample.py::test_field_is_dropped"}


def test_literal_without_a_now_relative_context_is_silent(tmp_path):
    offenders = _scan_source(
        tmp_path,
        """
        import datetime


        def test_csv_row_is_echoed():
            assert {"entry_date": FUTURE_DATE}
        """,
    )
    assert offenders == set()
