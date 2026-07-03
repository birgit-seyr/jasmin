"""Discovery-level guard: state-machine fields must not be touched
via ``QuerySet.update(...)`` / ``bulk_update(...)``.

Why this exists
---------------

Two models in this codebase enforce invariants inside ``save()``
that get silently skipped when callers use ``.update(...)`` instead:

* **``JasminUser.account_status``** — ``save()`` derives ``is_active``
  from ``account_status`` ("single source of truth") and stamps
  ``activated_at`` / ``inactivated_at`` on transitions. Bypass via
  ``.update(account_status="active")`` leaves ``is_active`` stale
  and the audit timestamps null.
* **``Member.admin_confirmed`` / ``Subscription.admin_confirmed``** —
  ``AdminConfirmableMixin.confirm()`` calls ``_post_confirm()``,
  which for ``Member`` generates the public ``member_number`` (the
  advisory-locked sequence from pass #7) and for ``Subscription``
  materialises shares + ShareDeliveries + ChargeSchedule. Bypass
  via ``.update(admin_confirmed=True)`` would leave a "confirmed"
  row with none of the downstream rows.

Greped at audit time and found **zero** active callers. This guard
exists so the bug can't be re-introduced silently — the bypass shape
is exactly the literal pattern, so a regex catches the realistic
risk.

How it works
------------

1. Walk every ``.py`` file under ``apps/`` (skipping ``tests/`` and
   ``migrations/``).
2. Tokenise and mask comments + string literals (so docstring text
   that mentions ``.update(account_status=...)`` doesn't match).
3. Regex for ``.update(...)`` / ``.bulk_update(...)`` calls whose
   kwargs include any of the protected field names within ~250
   chars (matches both single-line and broken-across-lines styles).
4. For each match, check the *raw* source line for an opt-out
   marker — see "Opt-out" below — and skip if present.
5. Assert no remaining offenders, with file:line for each.

Opt-out
-------

A legitimate batch update of one of these fields (e.g. a one-off
data migration; a deliberate ``last_login_ip`` bulk stamp on a
list of users) can opt out by adding a trailing-comment marker on
the same line as the ``.update(...)`` call::

    JasminUser.objects.filter(
        account_status="pending_invitation"
    ).update(account_status="inactive")  # state-field-update-allowed: prod cleanup 2026-05-24

The marker is a deliberate, greppable acknowledgement that the
caller knows the invariant is being skipped on purpose. The text
after the colon should explain *why* — the next reader will want
to know.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

# Locate the django-core root (this test lives at
# ``apps/authz/tests/test_state_field_update_bypass_guard.py``).
_DJANGO_CORE_ROOT = Path(__file__).resolve().parents[3]
_APPS_DIR = _DJANGO_CORE_ROOT / "apps"

_SKIP_DIRS: tuple[str, ...] = ("tests", "migrations", "__pycache__")
_SELF_PATH = Path(__file__).resolve()

# Field names whose Python-side ``save()`` invariants must not be
# bypassed via bulk ``update()``. ``account_status`` drives
# ``is_active`` / ``activated_at`` / ``inactivated_at`` on JasminUser;
# ``admin_confirmed`` drives ``_post_confirm`` side-effects on
# AdminConfirmableMixin consumers (Member, Subscription, ...).
_PROTECTED_FIELDS: tuple[str, ...] = ("account_status", "admin_confirmed")

# ``.update(`` or ``.bulk_update(`` (but NOT ``.update_or_create(`` —
# the trailing ``_or_create`` makes the regex's literal ``(`` fail to
# match), followed within 250 chars by ``<protected_field>=``. Window
# capped to keep multi-line method chains from spanning unrelated calls.
_PATTERN = re.compile(
    r"\.(?:bulk_update|update)\s*\((?:[^\n]{0,250}?)\b("
    + "|".join(_PROTECTED_FIELDS)
    + r")\s*=",
    re.DOTALL,
)

# Per-line opt-out marker. Searched in the raw (unmasked) source so a
# comment counts as a deliberate acknowledgement. The trailing text
# after the colon explains the rationale; the test enforces the prefix
# but doesn't parse the rationale.
_OPT_OUT_MARKER = "state-field-update-allowed"


def _mask_comments_and_strings(source: str) -> str:
    """Return ``source`` with comment and string-literal tokens replaced
    by spaces of the same dimensions. Preserves line/column positions
    so regex hits still report accurate line numbers.

    Falls back to raw source if the file fails to tokenise (syntax
    error mid-edit). Any real syntax error fails the rest of the test
    suite anyway.
    """
    lines = source.splitlines(keepends=True)
    mutable: list[list[str]] = [list(line) for line in lines]

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError):
        return source

    def _blank_chars_on_line(row: int, start_col: int, end_col: int) -> None:
        line = mutable[row]
        for col in range(start_col, min(end_col, len(line))):
            if line[col] != "\n":
                line[col] = " "

    for tok in tokens:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        start_row = tok.start[0] - 1
        start_col = tok.start[1]
        end_row = tok.end[0] - 1
        end_col = tok.end[1]

        if start_row == end_row:
            _blank_chars_on_line(start_row, start_col, end_col)
            continue

        _blank_chars_on_line(start_row, start_col, len(mutable[start_row]))
        for row in range(start_row + 1, end_row):
            _blank_chars_on_line(row, 0, len(mutable[row]))
        _blank_chars_on_line(end_row, 0, end_col)

    return "".join("".join(line) for line in mutable)


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _APPS_DIR.rglob("*.py"):
        if path.resolve() == _SELF_PATH:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def _line_at(text: str, position: int) -> tuple[int, str]:
    """Return (1-indexed line number, raw line text) for a byte offset."""
    line_no = text.count("\n", 0, position) + 1
    # Walk back to the start of the line.
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end == -1:
        line_end = len(text)
    return line_no, text[line_start:line_end]


def test_no_state_field_update_bypass() -> None:
    """Protected state-machine fields (``account_status``,
    ``admin_confirmed``) must not be modified via ``QuerySet.update(...)``
    or ``bulk_update(...)``. Those paths skip ``save()``, which is where
    the cross-column invariants live (see
    ``apps/accounts/models.py:JasminUser.save`` and
    ``apps/commissioning/models/mixin.py:AdminConfirmableMixin.confirm``).

    Use ``instance.save()`` per row, or add the
    ``state-field-update-allowed: <reason>`` marker as a trailing
    comment on the offending line if the bypass is deliberate.
    """
    offenders: list[str] = []
    for path in _iter_python_files():
        raw = path.read_text(encoding="utf-8")
        # Cheap reject: most files don't touch these names at all.
        if not any(f in raw for f in _PROTECTED_FIELDS):
            continue
        masked = _mask_comments_and_strings(raw)
        for match in _PATTERN.finditer(masked):
            line_no, raw_line = _line_at(raw, match.start())
            if _OPT_OUT_MARKER in raw_line:
                continue
            rel = path.relative_to(_DJANGO_CORE_ROOT)
            field = match.group(1)
            offenders.append(f"{rel}:{line_no}  (field: {field})")

    assert not offenders, (
        "Found bulk-update calls that bypass save()-enforced invariants on "
        "state-machine fields (comments and string literals are masked out "
        "before matching, so each hit is a real call). Use instance.save() "
        "per row, or add a trailing 'state-field-update-allowed: <reason>' "
        f"comment on the line if the bypass is deliberate. {len(offenders)} "
        "hit(s):"
        "\n  - " + "\n  - ".join(sorted(offenders))
    )
