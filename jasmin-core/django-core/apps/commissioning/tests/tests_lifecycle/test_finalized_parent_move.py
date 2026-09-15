"""Moving a reseller-document content line onto or off a finalized parent.

Inserting a line into a finalized parent is refused via ``PARENT_FK_FIELDS``
(see ``test_lifecycle_storno_and_inserts.py``). This file covers the UPDATE
side: re-pointing an EXISTING line's parent FK is refused when the old or the
new parent is finalized —

* at the Python layer (``FinalizedProtectedMixin.save``), which raises
  ``FinalizedError``, and
* at the database layer (the ``*_finalized_protect`` trigger functions rebuilt
  by migration ``0024_content_parent_move_protection``), which also catches
  ``QuerySet.update()`` and raw SQL.

A draft -> draft move keeps working on both layers.
"""

from __future__ import annotations

import datetime
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.commissioning.errors import FinalizedError
from apps.commissioning.models import (
    CrateContentInvoiceReseller,
    CrateDeliveryNoteContent,
    CrateOrderContent,
    DeliveryNoteContent,
    InvoiceResellerContent,
    OrderContent,
)
from apps.commissioning.models.mixin import FinalizedProtectedMixin
from apps.commissioning.services.delivery_note_service import DeliveryNoteService
from apps.commissioning.services.invoice_service import InvoiceService
from apps.commissioning.tests.factories import (
    CrateFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
    ShareArticleFactory,
)
from apps.shared.tenants.models import TenantSettings

_M0024 = importlib.import_module(
    "apps.commissioning.migrations.0024_content_parent_move_protection"
)

_TRIGGER_MESSAGE = "onto or off a finalized"


# ---------------------------------------------------------------------------
# Builders — each returns a fresh DRAFT parent and a DRAFT line on it
# ---------------------------------------------------------------------------
def _ensure_settings(tenant):
    TenantSettings.objects.get_or_create(
        tenant=tenant,
        valid_until=None,
        defaults=dict(
            tenant=tenant,
            valid_from=timezone.now() - datetime.timedelta(days=365),
            valid_until=None,
        ),
    )


def _draft_order():
    """A draft Order with one article line and one crate line."""
    order = OrderFactory(
        reseller=ResellerFactory(), year=2026, delivery_week=15, day_number=2
    )
    OrderContentFactory(
        order=order,
        share_article=ShareArticleFactory(),
        amount=Decimal("2"),
        price_per_unit=Decimal("3.00"),
        tax_rate=Decimal("7.00"),
        unit="KG",
        size="M",
    )
    CrateOrderContent.objects.create(
        order=order,
        crate_type=CrateFactory(),
        amount=2,
        price_per_unit=Decimal("1.50"),
        tax_rate=Decimal("19.00"),
    )
    return order


def _draft_delivery_note():
    # create_from_order finalizes the order; the delivery note stays a draft.
    return DeliveryNoteService.create_from_order(order=_draft_order())


def _draft_invoice():
    # create_from_delivery_note finalizes the delivery note; the invoice stays
    # a draft.
    return InvoiceService.create_from_delivery_note(
        delivery_note=_draft_delivery_note()
    )


def _order_with_article_line():
    order = _draft_order()
    return order, order.ordercontent_set.get()


def _order_with_crate_line():
    order = _draft_order()
    return order, order.crateordercontent_set.get()


def _order_content_with_crate_line():
    order_content = _draft_order().ordercontent_set.get()
    crate_line = CrateOrderContent.objects.create(
        order_content=order_content,
        crate_type=CrateFactory(),
        amount=1,
        price_per_unit=Decimal("1.50"),
        tax_rate=Decimal("19.00"),
    )
    return order_content, crate_line


def _delivery_note_with_article_line():
    delivery_note = _draft_delivery_note()
    return delivery_note, delivery_note.items.get()


def _delivery_note_with_crate_line():
    delivery_note = _draft_delivery_note()
    return delivery_note, delivery_note.crate_items.get()


def _invoice_with_article_line():
    invoice = _draft_invoice()
    return invoice, invoice.items.get()


def _invoice_with_crate_line():
    invoice = _draft_invoice()
    return invoice, invoice.crate_items.get()


@dataclass(frozen=True)
class LineCase:
    model: type
    parent_field: str
    build: Callable[[], tuple[Any, Any]]

    def __str__(self) -> str:
        return f"{self.model.__name__}.{self.parent_field}"


CASES = [
    LineCase(OrderContent, "order", _order_with_article_line),
    LineCase(CrateOrderContent, "order", _order_with_crate_line),
    LineCase(CrateOrderContent, "order_content", _order_content_with_crate_line),
    LineCase(DeliveryNoteContent, "delivery_note", _delivery_note_with_article_line),
    LineCase(CrateDeliveryNoteContent, "delivery_note", _delivery_note_with_crate_line),
    LineCase(InvoiceResellerContent, "invoice", _invoice_with_article_line),
    LineCase(CrateContentInvoiceReseller, "invoice", _invoice_with_crate_line),
]
CASE_IDS = [str(case) for case in CASES]


def _stored_parent_id(case: LineCase, line) -> str | None:
    attname = case.model._meta.get_field(case.parent_field).attname
    return case.model.objects.values_list(attname, flat=True).get(pk=line.pk)


def _queryset_repoint(case: LineCase, line, new_parent) -> None:
    """Re-point via ``QuerySet.update()`` inside a savepoint, so a trigger
    error rolls back only this block. The line itself is a draft, so the
    Python bulk guard lets the UPDATE through to the trigger."""
    with transaction.atomic():
        case.model.objects.filter(pk=line.pk).update(**{case.parent_field: new_parent})


# ===========================================================================
# Python layer — FinalizedProtectedMixin.save
# ===========================================================================
@pytest.mark.django_db
class TestSaveRefusesMoveAcrossFinalizedParent:
    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_draft_line_onto_finalized_parent_is_refused(self, tenant, case):
        _ensure_settings(connection.tenant)
        source_parent, line = case.build()
        target_parent, _ = case.build()
        target_parent.finalize()

        setattr(line, case.parent_field, target_parent)
        with pytest.raises(FinalizedError, match=_TRIGGER_MESSAGE):
            line.save()

        assert _stored_parent_id(case, line) == source_parent.pk

    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_draft_line_off_finalized_parent_is_refused(self, tenant, case):
        _ensure_settings(connection.tenant)
        source_parent, line = case.build()
        target_parent, _ = case.build()
        # Finalize only the parent row, leaving the line a draft on it.
        source_parent.finalize()

        setattr(line, case.parent_field, target_parent)
        with pytest.raises(FinalizedError, match=_TRIGGER_MESSAGE):
            line.save()

        assert _stored_parent_id(case, line) == source_parent.pk

    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_draft_to_draft_move_still_works(self, tenant, case):
        _ensure_settings(connection.tenant)
        _, line = case.build()
        target_parent, _ = case.build()

        setattr(line, case.parent_field, target_parent)
        line.save()

        assert _stored_parent_id(case, line) == target_parent.pk

    def test_update_fields_naming_the_parent_fk_is_refused(self, tenant):
        _ensure_settings(connection.tenant)
        _, line = _invoice_with_article_line()
        target_invoice, _ = _invoice_with_article_line()
        target_invoice.finalize()

        line.invoice = target_invoice
        with pytest.raises(FinalizedError, match=_TRIGGER_MESSAGE):
            line.save(update_fields=["invoice"])
        with pytest.raises(FinalizedError, match=_TRIGGER_MESSAGE):
            line.save(update_fields=["invoice_id"])

    def test_save_that_does_not_write_the_parent_fk_is_not_refused(self, tenant):
        """An in-memory parent change that the save does not write never
        reaches the database, so it is not a move."""
        _ensure_settings(connection.tenant)
        source_invoice, line = _invoice_with_article_line()
        target_invoice, _ = _invoice_with_article_line()
        target_invoice.finalize()

        line.invoice = target_invoice
        line.amount = Decimal("5")
        line.save(update_fields=["amount"])

        stored = InvoiceResellerContent.objects.get(pk=line.pk)
        assert stored.invoice_id == source_invoice.pk
        assert stored.amount == Decimal("5")


# ===========================================================================
# Database layer — the protection trigger (migration 0024)
# ===========================================================================
@pytest.mark.django_db
class TestTriggerRefusesMoveAcrossFinalizedParent:
    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_queryset_update_onto_finalized_parent_is_refused(self, tenant, case):
        _ensure_settings(connection.tenant)
        source_parent, line = case.build()
        target_parent, _ = case.build()
        target_parent.finalize()

        with pytest.raises(IntegrityError, match=_TRIGGER_MESSAGE):
            _queryset_repoint(case, line, target_parent)

        assert _stored_parent_id(case, line) == source_parent.pk

    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_queryset_update_off_finalized_parent_is_refused(self, tenant, case):
        _ensure_settings(connection.tenant)
        source_parent, line = case.build()
        target_parent, _ = case.build()
        source_parent.finalize()

        with pytest.raises(IntegrityError, match=_TRIGGER_MESSAGE):
            _queryset_repoint(case, line, target_parent)

        assert _stored_parent_id(case, line) == source_parent.pk

    @pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
    def test_queryset_update_draft_to_draft_still_works(self, tenant, case):
        _ensure_settings(connection.tenant)
        _, line = case.build()
        target_parent, _ = case.build()

        _queryset_repoint(case, line, target_parent)

        assert _stored_parent_id(case, line) == target_parent.pk

    def test_raw_sql_move_onto_finalized_parent_is_refused(self, tenant):
        _ensure_settings(connection.tenant)
        source_invoice, line = _invoice_with_article_line()
        target_invoice, _ = _invoice_with_article_line()
        target_invoice.finalize()

        with pytest.raises(IntegrityError, match=_TRIGGER_MESSAGE):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE commissioning_invoiceresellercontent "
                    "SET invoice_id = %s WHERE id = %s",
                    [target_invoice.pk, line.pk],
                )

        assert (
            InvoiceResellerContent.objects.get(pk=line.pk).invoice_id
            == source_invoice.pk
        )

    def test_unrelated_column_update_on_draft_line_of_finalized_parent_passes(
        self, tenant
    ):
        """The parent check only fires when the parent FK changes."""
        _ensure_settings(connection.tenant)
        invoice, line = _invoice_with_article_line()
        invoice.finalize()

        InvoiceResellerContent.objects.filter(pk=line.pk).update(note="kept")

        assert InvoiceResellerContent.objects.get(pk=line.pk).note == "kept"


# ===========================================================================
# Nullable parent FK — present and absent
# ===========================================================================
@pytest.mark.django_db
class TestNullableParentFk:
    """``CrateDeliveryNoteContent.delivery_note`` is nullable: a line can be
    detached (FK -> NULL) or attached (NULL -> FK)."""

    def _orphan_crate_line(self):
        return CrateDeliveryNoteContent.objects.create(
            delivery_note=None,
            crate_type=CrateFactory(),
            amount=1,
            price_per_unit=Decimal("1.50"),
            tax_rate=Decimal("19.00"),
        )

    def test_detaching_from_finalized_parent_is_refused(self, tenant):
        _ensure_settings(connection.tenant)
        delivery_note, line = _delivery_note_with_crate_line()
        delivery_note.finalize()

        line.delivery_note = None
        with pytest.raises(FinalizedError, match=_TRIGGER_MESSAGE):
            line.save()
        with pytest.raises(IntegrityError, match=_TRIGGER_MESSAGE):
            with transaction.atomic():
                CrateDeliveryNoteContent.objects.filter(pk=line.pk).update(
                    delivery_note=None
                )

        stored = CrateDeliveryNoteContent.objects.get(pk=line.pk)
        assert stored.delivery_note_id == delivery_note.pk

    def test_attaching_orphan_to_finalized_parent_is_refused(self, tenant):
        _ensure_settings(connection.tenant)
        line = self._orphan_crate_line()
        delivery_note, _ = _delivery_note_with_crate_line()
        delivery_note.finalize()

        line.delivery_note = delivery_note
        with pytest.raises(FinalizedError, match=_TRIGGER_MESSAGE):
            line.save()
        with pytest.raises(IntegrityError, match=_TRIGGER_MESSAGE):
            with transaction.atomic():
                CrateDeliveryNoteContent.objects.filter(pk=line.pk).update(
                    delivery_note=delivery_note
                )

        assert CrateDeliveryNoteContent.objects.get(pk=line.pk).delivery_note_id is None

    def test_attaching_and_detaching_draft_parent_still_works(self, tenant):
        _ensure_settings(connection.tenant)
        line = self._orphan_crate_line()
        delivery_note, _ = _delivery_note_with_crate_line()

        line.delivery_note = delivery_note
        line.save()
        stored = CrateDeliveryNoteContent.objects.get(pk=line.pk)
        assert stored.delivery_note_id == delivery_note.pk

        CrateDeliveryNoteContent.objects.filter(pk=line.pk).update(delivery_note=None)
        assert CrateDeliveryNoteContent.objects.get(pk=line.pk).delivery_note_id is None


# ===========================================================================
# Contract: models <-> migration map <-> live trigger
# ===========================================================================
def _models_with_parent_fks() -> list[type]:
    from django.apps import apps as django_apps

    return [
        model
        for model in django_apps.get_models()
        if issubclass(model, FinalizedProtectedMixin)
        and not model._meta.abstract
        and model.PARENT_FK_FIELDS
    ]


def _expected_parent_columns(model) -> list[tuple[str, str]]:
    return [
        (
            model._meta.get_field(name).column,
            model._meta.get_field(name).related_model._meta.db_table,
        )
        for name in model.PARENT_FK_FIELDS
    ]


class TestMigrationParentMapMatchesModels:
    def test_every_model_with_parent_fks_is_covered(self):
        tables = {model._meta.db_table for model in _models_with_parent_fks()}
        assert tables == set(_M0024.CONTENT_TABLE_PARENTS)

    def test_parent_columns_match_parent_fk_fields(self):
        for model in _models_with_parent_fks():
            assert _M0024.CONTENT_TABLE_PARENTS[
                model._meta.db_table
            ] == _expected_parent_columns(model), model.__name__


@pytest.mark.django_db
class TestLiveTriggerCarriesParentMoveGuard:
    """A later rebuild of a content table's trigger function that drops the
    parent-move block (e.g. copied from 0002 or 0015) fails here."""

    def test_trigger_checks_every_parent_fk_column(self, tenant):
        for model in _models_with_parent_fks():
            table = model._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_get_functiondef(p.oid) "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE p.proname = %s AND n.nspname = %s",
                    [f"{table}_finalized_protect", connection.schema_name],
                )
                row = cursor.fetchone()
            assert row, f"trigger function for {table} not found"
            body = row[0]
            for column, parent_table in _expected_parent_columns(model):
                assert (
                    f"NEW.{column} IS DISTINCT FROM OLD.{column}" in body
                ), f"{table}: trigger lacks the parent-move guard for {column}"
                assert (
                    f"FROM %I.{parent_table} WHERE" in body
                ), f"{table}: trigger does not look up {parent_table}"
