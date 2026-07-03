"""Guardrail: the FinalizedProtected Python allowlist == the Postgres trigger.

Each ``FinalizedProtectedMixin`` model carries two parallel allowlists of
columns that may still change after ``is_finalized=True``:

  1. Python — ``Model.ALLOWED_FINALIZED_UPDATES`` (checked in ``save()``).
  2. Postgres — a ``BEFORE UPDATE/DELETE`` trigger function installed via
     RunSQL, with its allowed-column array baked into the function body
     (``apps/commissioning/migrations/0002_finalized_protection_and_reference_data.py``,
     the post-squash installer that folded in the old 0007/0019/0020/0032 chain).

CLAUDE.md warns these MUST stay in sync and that ``makemigrations`` is blind
to RunSQL triggers, so drift is silent: a column Python now allows but the
trigger still rejects surfaces only as a runtime ``IntegrityError``; the
reverse is a silent immutability bypass via ``.objects.update()`` / raw SQL.

This test introspects the LIVE trigger function body per protected table and
asserts its allowed-column set equals ``ALLOWED_FINALIZED_UPDATES`` (mapped
field-name -> DB column). It converts "silent until production" into a CI
failure: any change to ``ALLOWED_FINALIZED_UPDATES`` without the follow-up
trigger-rebuild migration fails here.
"""

from __future__ import annotations

import re

import pytest
from django.db import connection

from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    DeliveryNoteContent,
    DeliveryNoteReseller,
    InvoiceReseller,
    InvoiceResellerContent,
    Offer,
    Order,
    OrderContent,
)

# Every model guarded by FinalizedProtectedMixin (all in models/resellers.py).
PROTECTED_MODELS = [
    Offer,
    Order,
    OrderContent,
    CrateOrderContent,
    CrateDeliveryNoteContent,
    CrateContentInvoiceReseller,
    DeliveryNoteContent,
    InvoiceResellerContent,
    DeliveryNoteReseller,
    InvoiceReseller,
]

# The trigger declares ``allowed text[] := ARRAY['c1', 'c2', ...]::text[];``
# (see migration 0002_finalized_protection_and_reference_data
# ``_build_function_sql`` / ``_build_allowed_array_literal``).
_ALLOWED_ARRAY_RE = re.compile(
    r"allowed\s+text\[\]\s*:=\s*ARRAY\[(.*?)\]::text\[\]", re.DOTALL
)


def _trigger_function_def(table: str) -> str:
    """Return the live ``pg_get_functiondef`` body of a table's protect fn."""
    fn_name = f"{table}_finalized_protect"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_functiondef(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE p.proname = %s AND n.nspname = %s",
            [fn_name, connection.schema_name],
        )
        row = cursor.fetchone()
    assert row, (
        f"trigger function {fn_name} not found in schema "
        f"{connection.schema_name} — finalization protection migration "
        "missing?"
    )
    return row[0]


def _trigger_allowlist(table: str) -> set[str]:
    """Parse the allowed-column set out of the live trigger function body."""
    fn_name = f"{table}_finalized_protect"
    match = _ALLOWED_ARRAY_RE.search(_trigger_function_def(table))
    assert match, f"could not locate the allowed[] array literal in {fn_name}"
    cols = set(re.findall(r"'([^']*)'", match.group(1)))
    # ``is_finalized`` is always appended by the migration helper (the flag
    # itself must be flippable); it is not part of ALLOWED_FINALIZED_UPDATES.
    cols.discard("is_finalized")
    return cols


def _trigger_is_one_way(table: str) -> bool:
    """True iff the live trigger body carries the one-way unfinalize guard.

    ``_build_function_sql(one_way=True)`` (migration 0002_finalized_protection_and_reference_data) is the only
    place the body raises ``Cannot unfinalize`` — the
    ``OLD.is_finalized AND NOT NEW.is_finalized`` RAISE block.
    """
    return "Cannot unfinalize" in _trigger_function_def(table)


def _python_allowlist(model) -> set[str]:
    """``ALLOWED_FINALIZED_UPDATES`` as DB column names.

    The Python list holds FIELD names; the trigger holds DB COLUMNs. They
    differ for FKs (e.g. ``cancelled_by_invoice`` -> ``cancelled_by_invoice_id``
    on ``InvoiceReseller``), so translate before comparing.
    """
    return {
        model._meta.get_field(field).column for field in model.ALLOWED_FINALIZED_UPDATES
    }


@pytest.mark.django_db
class TestFinalizedAllowlistSync:
    @pytest.mark.parametrize(
        "model", PROTECTED_MODELS, ids=[m.__name__ for m in PROTECTED_MODELS]
    )
    def test_python_allowlist_matches_trigger(self, tenant, model):
        table = model._meta.db_table
        python_cols = _python_allowlist(model)
        trigger_cols = _trigger_allowlist(table)
        assert python_cols == trigger_cols, (
            f"{model.__name__} ({table}): ALLOWED_FINALIZED_UPDATES (as DB "
            f"columns) {sorted(python_cols)} != trigger allowlist "
            f"{sorted(trigger_cols)}. The Python and Postgres allowlists have "
            "drifted — rebuild the trigger with a follow-up migration "
            "mirroring _build_function_sql from migration 0002_finalized_protection_and_reference_data (see the "
            "FinalizedProtectedMixin note in CLAUDE.md)."
        )

    @pytest.mark.parametrize(
        "model", PROTECTED_MODELS, ids=[m.__name__ for m in PROTECTED_MODELS]
    )
    def test_trigger_one_way_matches_model(self, tenant, model):
        """The OTHER half of the contract: ``IS_FINALIZED_ONE_WAY`` on the model
        must equal whether the trigger emits the one-way unfinalize guard.

        Without this, a model that gains/loses ``IS_FINALIZED_ONE_WAY`` without
        a follow-up trigger rebuild stays green here while Python and Postgres
        disagree on whether a finalized row may be un-finalized.
        """
        table = model._meta.db_table
        expected = bool(getattr(model, "IS_FINALIZED_ONE_WAY", False))
        actual = _trigger_is_one_way(table)
        assert actual == expected, (
            f"{model.__name__} ({table}): IS_FINALIZED_ONE_WAY={expected} but the "
            f"trigger {'HAS' if actual else 'LACKS'} the one-way unfinalize "
            "guard. Rebuild the trigger with one_way matching the model "
            "(see _build_function_sql in migration 0002_finalized_protection_and_reference_data and the "
            "FinalizedProtectedMixin note in CLAUDE.md)."
        )


@pytest.mark.django_db
class TestProtectedModelListComplete:
    """Meta-guard: ``PROTECTED_MODELS`` above must equal the LIVE set of concrete
    ``FinalizedProtectedMixin`` subclasses. Without this, a NEW finalizable
    model (e.g. a member credit note) added with the mixin but forgotten from
    both the trigger-install migration and this list would run with Python-only
    protection — the exact silent ``.objects.update()`` / raw-SQL bypass the
    guardrail exists to convert into a CI failure — while the parametrized sync
    tests above never look at it."""

    def test_protected_models_list_covers_every_mixin_subclass(self, tenant):
        from django.apps import apps as django_apps

        from apps.commissioning.models.mixin import FinalizedProtectedMixin

        live = {
            model
            for model in django_apps.get_models()
            if issubclass(model, FinalizedProtectedMixin) and not model._meta.abstract
        }
        registered = set(PROTECTED_MODELS)

        unregistered = live - registered
        stale = registered - live
        assert not unregistered and not stale, (
            "FinalizedProtectedMixin allowlist drift.\n"
            "  In the codebase but MISSING from PROTECTED_MODELS (also needs a "
            "trigger-install migration + ALLOWED_FINALIZED_UPDATES): "
            f"{sorted(m.__name__ for m in unregistered)}\n"
            "  In PROTECTED_MODELS but no longer a mixin subclass (renamed / "
            f"removed): {sorted(m.__name__ for m in stale)}"
        )
