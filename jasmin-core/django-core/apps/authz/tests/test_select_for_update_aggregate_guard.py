"""Discovery-level guard against ``select_for_update() + aggregate()``.

Why this exists
---------------

Postgres silently ignores ``FOR UPDATE`` on aggregate queries — the
lock is never taken, but the code reads like it is. The canonical
``FinalizableDocumentMixin`` docstring (``apps/commissioning/models/
mixin.py``, lines ~730) explicitly calls this out and prescribes
``pg_advisory_xact_lock`` as the alternative.

The race-conditions audit pass (see ``docs/code/engineering-audit-playbook.md``,
Pass #7) found three sites where this pattern had crept back in:

  * ``Member._generate_member_number``
  * ``CrateContentService.apply_total_amount_change``
  * ``GenericDocumentationService._sum_theoretical``

All three were fixed in the same audit pass. This test exists so the
fourth one is caught at write time, not by the next audit.

How it works
------------

Walks every ``.py`` file under ``apps/`` (skipping ``tests/`` and
``migrations/``), normalises whitespace, and greps for
``select_for_update`` followed by ``.aggregate(`` within a short
window. There is no legitimate use of this combination in this
codebase — any hit is a bug.

The whitespace normalisation handles the realistic shapes:

    qs.select_for_update().aggregate(Sum(...))           # one line
    qs.select_for_update().filter(...).aggregate(...)    # filter in between
    (qs
       .select_for_update()
       .aggregate(total=Sum("amount")))                  # broken across lines

A 250-char window covers all reasonable formatting; the
``select_for_update().filter(...).aggregate(...)`` chain rarely
exceeds 200 chars even with long table names.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

# Locate the django-core root (this test lives at
# ``apps/authz/tests/test_select_for_update_aggregate_guard.py``).
_DJANGO_CORE_ROOT = Path(__file__).resolve().parents[3]
_APPS_DIR = _DJANGO_CORE_ROOT / "apps"

# Directories where the pattern is acceptable (audit doc references it,
# tests may demonstrate it deliberately for documentation purposes).
_SKIP_DIRS: tuple[str, ...] = ("tests", "migrations", "__pycache__")

# Self-exclusion: this file mentions ``select_for_update`` /
# ``aggregate`` in docstring text and would otherwise self-match
# even after string-masking (the regex below mentions both names).
_SELF_PATH = Path(__file__).resolve()

# ``select_for_update`` ... (anything) ... ``.aggregate(``
# Window capped at 250 chars so we don't span unrelated method chains.
_PATTERN = re.compile(
    r"select_for_update\s*\([^)]*\)(?:[^\n]{0,250}?)\.aggregate\s*\(",
    re.DOTALL,
)


def _mask_comments_and_strings(source: str) -> str:
    """Return ``source`` with comment and string-literal tokens
    replaced by spaces of the same dimensions.

    Line and column positions are preserved so regex matches against
    the masked output still yield accurate line numbers in error
    messages. Without this, the guard would false-positive on its
    own explanatory comments (e.g. a fix's docstring that reads
    "the previous code chained ``select_for_update().aggregate(...)``").

    Falls back to the raw source if the file fails to tokenise
    (syntax error, unfinished edit). A real syntax error will fail
    the rest of the test suite anyway.
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
        # tokenize rows are 1-indexed; columns are 0-indexed.
        start_row = tok.start[0] - 1
        start_col = tok.start[1]
        end_row = tok.end[0] - 1
        end_col = tok.end[1]

        if start_row == end_row:
            _blank_chars_on_line(start_row, start_col, end_col)
            continue

        # Multi-line string: blank out the trailing portion of the
        # start row, every middle row, and the leading portion of
        # the end row.
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


def test_no_select_for_update_chained_to_aggregate() -> None:
    """``select_for_update().aggregate(...)`` is a Postgres no-op.

    Postgres silently ignores FOR UPDATE on aggregate queries — the
    lock is never taken. Use ``pg_advisory_xact_lock`` instead (see
    ``FinalizableDocumentMixin.save_with_number_retry`` for the
    canonical pattern, and the 2026-05-24 race-conditions audit for
    the backstory).
    """
    offenders: list[str] = []
    for path in _iter_python_files():
        raw = path.read_text(encoding="utf-8")
        # Cheap reject for the ~99% of files that don't even use
        # select_for_update — skips both the tokenize cost and the
        # subsequent regex evaluation.
        if "select_for_update" not in raw:
            continue
        masked = _mask_comments_and_strings(raw)
        for match in _PATTERN.finditer(masked):
            line_no = masked.count("\n", 0, match.start()) + 1
            rel = path.relative_to(_DJANGO_CORE_ROOT)
            offenders.append(f"{rel}:{line_no}")

    assert not offenders, (
        "Found ``select_for_update().aggregate(...)`` chains in code "
        "(comments and string literals are masked out before matching, "
        "so each hit is a real call). Postgres silently ignores FOR "
        "UPDATE on aggregate queries, so these take no lock. Use "
        "``pg_advisory_xact_lock`` instead (see "
        "``FinalizableDocumentMixin.save_with_number_retry`` for the "
        f"canonical pattern). {len(offenders)} hit(s):"
        "\n  - " + "\n  - ".join(sorted(offenders))
    )
