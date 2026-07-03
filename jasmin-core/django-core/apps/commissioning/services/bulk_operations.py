"""Shared per-item-savepoint loop for bulk endpoints with partial success.

A bulk endpoint runs under an outer ``@transaction.atomic`` and loops over
items, collecting per-item errors for a 207 Multi-Status response. Without a
per-item savepoint that contract silently breaks: the first real
``IntegrityError`` / ``DataError`` marks the whole PostgreSQL transaction
aborted, every later query raises ``TransactionManagementError``, and the
outer atomic rolls back the successful items too — a 500 instead of a 207.

``bulk_with_savepoints`` owns that loop skeleton once. The except-set and the
error recording are parametrized because the callers legitimately diverge in
what they treat as a per-item failure (e.g. only the finalize family collects
``JasminError``; only the reseller bulk collects ``ConflictError``) — this
helper unifies the control flow, not the exception policy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from django.db import transaction

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


def bulk_with_savepoints(
    items: Iterable[ItemT],
    handler: Callable[[ItemT], ResultT],
    *,
    catch: tuple[type[Exception], ...],
    on_error: Callable[[ItemT, Exception], None],
    on_success: Callable[[ItemT, ResultT], None] | None = None,
) -> None:
    """Run ``handler(item)`` for each item inside its own savepoint.

    Must be called under an outer ``transaction.atomic`` (the view's
    ``@transaction.atomic``) so the nested atomic here becomes a SAVEPOINT: a
    failing item rolls back only itself and the connection stays usable for
    the rest of the batch.

    ``handler`` does one item's DB work. Success bookkeeping (counters,
    success rows) must never survive a rolled-back savepoint, so do it either
    at the END of ``handler`` (after the last write) or in ``on_success(item,
    result)``, which receives ``handler``'s return value and runs only after
    the savepoint was released cleanly.

    Any exception in ``catch`` that escapes the savepoint is passed to
    ``on_error(item, exc)`` — typically appending a per-item error row — and
    the loop continues. Exceptions outside ``catch`` propagate and abort the
    batch, as they should.
    """
    for item in items:
        try:
            with transaction.atomic():
                result = handler(item)
        except catch as exc:
            on_error(item, exc)
        else:
            if on_success is not None:
                on_success(item, result)
