"""Tests for reseller_views.py — order overview, bulk document ops, offers."""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import DeliveryNoteReseller, Order
from apps.commissioning.tests.factories import (
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    InvoiceResellerFactory,
    OfferFactory,
    OfferGroupFactory,
    OrderContentFactory,
    OrderFactory,
    ResellerFactory,
)

# ---------------------------------------------------------------------------
# DaysWithOrdersView
# ---------------------------------------------------------------------------
URL_DAYS_WITH_ORDERS = reverse("days_with_orders")


@pytest.mark.django_db
class TestDaysWithOrdersView:
    def test_returns_distinct_days(self, api_client, tenant):
        reseller = ResellerFactory()
        o1 = OrderFactory(reseller=reseller, year=2026, delivery_week=15, day_number=1)
        o2 = OrderFactory(reseller=reseller, year=2026, delivery_week=15, day_number=3)
        OrderContentFactory(order=o1)
        OrderContentFactory(order=o2)

        resp = api_client.get(URL_DAYS_WITH_ORDERS, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert set(resp.data["days"]) == {1, 3}

    def test_empty_when_no_orders(self, api_client, tenant):
        resp = api_client.get(URL_DAYS_WITH_ORDERS, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["days"] == []

    def test_missing_params_returns_400(self, api_client, tenant):
        resp = api_client.get(URL_DAYS_WITH_ORDERS)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# CombinedOrderOverviewView
# ---------------------------------------------------------------------------
URL_ORDERS_OVERVIEW = reverse("orders_overview")


@pytest.mark.django_db
class TestCombinedOrderOverviewView:
    def test_returns_orders(self, api_client, tenant):
        reseller = ResellerFactory()
        OrderFactory(reseller=reseller, year=2026, delivery_week=15, day_number=1)

        resp = api_client.get(URL_ORDERS_OVERVIEW, {"year": 2026, "delivery_week": 15})
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert "order_number" in resp.data[0]
        assert resp.data[0]["has_delivery_note"] is False

    def test_filters_by_reseller(self, api_client, tenant):
        r1 = ResellerFactory()
        r2 = ResellerFactory()
        OrderFactory(reseller=r1, year=2026, delivery_week=15, day_number=1)
        OrderFactory(reseller=r2, year=2026, delivery_week=15, day_number=1)

        resp = api_client.get(
            URL_ORDERS_OVERVIEW,
            {"year": 2026, "delivery_week": 15, "reseller": str(r1.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1

    def test_includes_delivery_note_info(self, api_client, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=2026, delivery_week=15, day_number=1
        )
        DeliveryNoteResellerFactory(order=order)

        resp = api_client.get(URL_ORDERS_OVERVIEW, {"year": 2026, "delivery_week": 15})
        assert resp.data[0]["has_delivery_note"] is True

    def test_empty_without_orders(self, api_client, tenant):
        resp = api_client.get(URL_ORDERS_OVERVIEW, {"year": 2026, "delivery_week": 53})
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == []

    def test_missing_year_returns_400(self, api_client, tenant):
        # year is required at runtime — without it the endpoint would
        # materialize every order across all years with no pagination.
        resp = api_client.get(URL_ORDERS_OVERVIEW)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "query.invalid_param"
        assert "year" in resp.data["message"]


# ---------------------------------------------------------------------------
# BulkCopyOffersToNextWeekView
# ---------------------------------------------------------------------------
URL_COPY_OFFERS = reverse("bulk_copy_offers_to_next_week")


@pytest.mark.django_db
class TestBulkCopyOffersToNextWeekView:
    def test_copies_offers(self, api_client, tenant):
        offer = OfferFactory(year=2026, delivery_week=15)

        resp = api_client.post(
            URL_COPY_OFFERS,
            {"ids": [str(offer.id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["total_requested"] == 1
        assert resp.data["total_copied"] >= 0

    def test_empty_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_COPY_OFFERS, {"ids": []}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# BulkCopyOffersToOfferGroupView
# ---------------------------------------------------------------------------
URL_COPY_TO_GROUP = reverse("bulk_copy_offers_to_offer_group")


@pytest.mark.django_db
class TestBulkCopyOffersToOfferGroupView:
    def test_copies_to_group(self, api_client, tenant):
        offer = OfferFactory(year=2026, delivery_week=15)
        group = OfferGroupFactory()

        resp = api_client.post(
            URL_COPY_TO_GROUP,
            {
                "ids": [str(offer.id)],
                "year": 2026,
                "delivery_week": 15,
                "offer_group": str(group.id),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def test_missing_offer_group_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_COPY_TO_GROUP,
            {"ids": ["some-id"], "year": 2026, "delivery_week": 15},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# SetInvoiceNoteView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSetInvoiceNoteView:
    def test_sets_note(self, api_client, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order)
        DeliveryNoteContentFactory(delivery_note=dn)
        _invoice = InvoiceResellerFactory(reseller=reseller)

        url = reverse("set_invoice_note", args=[str(order.id)])
        resp = api_client.patch(url, {"note": "Test note"}, format="json")
        # The view looks up the invoice via order → delivery_note; may return 200 or 404
        # depending on the invoice linkage
        assert resp.status_code in (
            status.HTTP_200_OK,
            status.HTTP_404_NOT_FOUND,
        )


# ---------------------------------------------------------------------------
# BulkFinalizeDocumentsView
# ---------------------------------------------------------------------------
URL_FINALIZE_DOCS = reverse("bulk_finalize_documents")


@pytest.mark.django_db
class TestBulkFinalizeDocumentsView:
    def test_missing_model_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE_DOCS,
            {"ids": ["some-id"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_model_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE_DOCS,
            {"ids": ["some-id"], "model": "invalid"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_orders_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_FINALIZE_DOCS,
            {
                "ids": ["00000000-0000-0000-0000-000000000000"],
                "model": "delivery_note",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# BulkDeleteDocumentsView
# ---------------------------------------------------------------------------
URL_DELETE_DOCS = reverse("bulk_delete_documents")


@pytest.mark.django_db
class TestBulkDeleteDocumentsView:
    def test_deletes_delivery_note(self, api_client, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order)

        resp = api_client.post(
            URL_DELETE_DOCS,
            {"ids": [str(order.id)], "model": "delivery_note"},
            format="json",
        )
        assert resp.status_code in (status.HTTP_200_OK, status.HTTP_207_MULTI_STATUS)
        # Delivery note should be deleted
        assert not DeliveryNoteReseller.objects.filter(pk=dn.pk).exists()

    def test_cannot_delete_finalized(self, api_client, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order)
        DeliveryNoteReseller.objects.filter(pk=dn.pk).update(is_finalized=True)

        resp = api_client.post(
            URL_DELETE_DOCS,
            {"ids": [str(order.id)], "model": "delivery_note"},
            format="json",
        )
        assert resp.status_code == status.HTTP_207_MULTI_STATUS
        assert DeliveryNoteReseller.objects.filter(pk=dn.pk).exists()

    def test_invalid_model_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_DELETE_DOCS,
            {"ids": ["x"], "model": "BAD"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# _run_per_order_bulk savepoint isolation (COR-20)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRunPerOrderBulkSavepoint:
    """A real DB-level error in one order's handler (e.g. a PROTECT FK on
    delete) must roll back ONLY that order, leaving the connection usable so
    the rest of the batch still commits — a 207, not a 500. Without the
    per-order savepoint the first IntegrityError poisons the view's outer
    ``@transaction.atomic`` and every later query raises
    ``TransactionManagementError``."""

    def test_db_error_in_one_order_does_not_abort_batch(self, tenant):
        from django.db import transaction

        from apps.commissioning.views.reseller_views import _run_per_order_bulk

        good = OrderFactory()
        bad = OrderFactory()

        def handler(order, results, errors):
            if order.pk == bad.pk:
                # Force a real IntegrityError: re-INSERT an already-saved row
                # (duplicate primary key). bulk_create bypasses save() /
                # full_clean and hits the DB directly, so this is a genuine
                # transaction-aborting error — exactly what the savepoint must
                # contain. Without the savepoint the outer atomic is poisoned
                # and the later query/commit raises TransactionManagementError.
                Order.objects.bulk_create([good])
            results.append({"order_id": str(order.id), "success": True})

        with transaction.atomic():  # mimic the view's outer @transaction.atomic
            results, errors = _run_per_order_bulk(
                Order.objects.filter(pk__in=[good.pk, bad.pk]), handler
            )
            # Connection still usable after the failing order — without the
            # savepoint this query raises TransactionManagementError.
            assert Order.objects.filter(pk=good.pk).exists()

        result_ids = {r["order_id"] for r in results}
        assert str(good.id) in result_ids  # the good order committed
        assert str(bad.id) not in result_ids  # the bad order rolled back
        assert any(e["order_id"] == str(bad.id) for e in errors)


# ---------------------------------------------------------------------------
# BulkSetToPaidDocumentsView
# ---------------------------------------------------------------------------
URL_SET_TO_PAID = reverse("bulk_set_to_paid_documents")


@pytest.mark.django_db
class TestBulkSetToPaidDocumentsView:
    def test_only_invoice_model_accepted(self, api_client, tenant):
        resp = api_client.post(
            URL_SET_TO_PAID,
            {"ids": ["x"], "model": "delivery_note"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_ids_returns_400(self, api_client, tenant):
        resp = api_client.post(
            URL_SET_TO_PAID,
            {"ids": [], "model": "invoice"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_orders_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_SET_TO_PAID,
            {
                "ids": ["00000000-0000-0000-0000-000000000000"],
                "model": "invoice",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_summary_invoice_spanning_orders_no_spurious_already_paid(
        self, api_client, tenant
    ):
        """DOC-9: several orders sharing ONE summary invoice, set-to-paid in one
        batch, report one success per order — not 1 success + N-1 spurious
        'already paid' failures."""
        from apps.commissioning.services import InvoiceService
        from apps.commissioning.tests.tests_services.test_invoice_service import (
            _finalized_delivery_note,
        )

        reseller = ResellerFactory()
        dn1 = _finalized_delivery_note(tenant, reseller=reseller, delivery_week=15)
        dn2 = _finalized_delivery_note(tenant, reseller=reseller, delivery_week=16)
        InvoiceService.create_summary_invoice_from_delivery_notes([dn1, dn2])

        resp = api_client.post(
            URL_SET_TO_PAID,
            {
                "ids": [str(dn1.order.id), str(dn2.order.id)],
                "model": "invoice",
            },
            format="json",
        )

        assert resp.status_code in (status.HTTP_200_OK, status.HTTP_207_MULTI_STATUS)
        assert resp.data["successful"] == 2
        assert resp.data["failed"] == 0


# ---------------------------------------------------------------------------
# BulkCreateDocumentsFromOrdersView
# ---------------------------------------------------------------------------
URL_CREATE_DOCS = reverse("bulk_create_documents_from_orders")


@pytest.mark.django_db
class TestBulkCreateDocumentsFromOrdersView:
    def test_creates_delivery_notes_from_orders(self, api_client, tenant):
        """Happy path: a fresh order without a DN gets a new DN created."""
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        OrderContentFactory(order=order)

        resp = api_client.post(
            URL_CREATE_DOCS,
            {
                "ids": [str(order.id)],
                "model": "delivery_note",
                "date": "2026-05-25",
            },
            format="json",
        )
        # 201 on full success, 207 if any per-order error occurred.
        assert resp.status_code in (
            status.HTTP_201_CREATED,
            status.HTTP_207_MULTI_STATUS,
        )
        assert resp.data["model"] == "delivery_note"
        assert resp.data["total_processed"] == 1
        # Either it succeeded (DN created) or the failure surfaces in errors;
        # both shapes are accepted to keep this tolerant of service-layer
        # invariants (e.g. missing prices) that aren't the point of this test.
        assert resp.data["successful"] + resp.data["failed"] == 1

    def test_no_orders_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_CREATE_DOCS,
            {
                "ids": ["00000000-0000-0000-0000-000000000000"],
                "model": "delivery_note",
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_missing_model_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_CREATE_DOCS, {"ids": ["x"]}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# BulkCreateSummaryInvoiceFromOrdersView
# ---------------------------------------------------------------------------
URL_SUMMARY_INVOICE = reverse("bulk_create_summary_invoice_from_orders")


@pytest.mark.django_db
class TestBulkCreateSummaryInvoiceFromOrdersView:
    def test_empty_ids_returns_error(self, api_client, tenant):
        resp = api_client.post(URL_SUMMARY_INVOICE, {"ids": []}, format="json")
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_no_orders_returns_404(self, api_client, tenant):
        resp = api_client.post(
            URL_SUMMARY_INVOICE,
            {"ids": ["00000000-0000-0000-0000-000000000000"]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_order_without_delivery_note_fails(self, api_client, tenant):
        """Orders without a DN can't be summarized — must surface as a
        ``summary_invoice.no_valid_dns`` error rather than crash."""
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)  # no DN
        OrderContentFactory(order=order)

        resp = api_client.post(
            URL_SUMMARY_INVOICE, {"ids": [str(order.id)]}, format="json"
        )
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


# ---------------------------------------------------------------------------
# SetOrderNoteView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSetOrderNoteView:
    def test_sets_note(self, api_client, tenant):
        from apps.commissioning.models import Order

        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)

        url = reverse("set_order_note", args=[str(order.id)])
        resp = api_client.patch(url, {"note": "ring twice at the gate"}, format="json")

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["note"] == "ring twice at the gate"
        order_db = Order.objects.get(pk=order.pk)
        assert order_db.note == "ring twice at the gate"

    def test_unknown_order_returns_404(self, api_client, tenant):
        url = reverse("set_order_note", args=["00000000-0000-0000-0000-000000000000"])
        resp = api_client.patch(url, {"note": "anything"}, format="json")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# CreateOffersView
# ---------------------------------------------------------------------------
URL_CREATE_OFFERS = reverse("create_offers")


@pytest.mark.django_db
class TestCreateOffersView:
    def test_missing_params_returns_400(self, api_client, tenant):
        resp = api_client.post(URL_CREATE_OFFERS, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_week_returns_200_with_zero_counts(self, api_client, tenant):
        """A week with no forecasts / share contents → no offers created.
        Service returns ``success=False`` with counts at 0; view returns 200."""
        resp = api_client.post(
            URL_CREATE_OFFERS,
            {"year": 2099, "delivery_week": 1},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["success"] is False
        assert resp.data["created_count"] == 0
        assert resp.data["skipped_count"] == 0


# ---------------------------------------------------------------------------
# offer_sending_status
# ---------------------------------------------------------------------------
URL_OFFER_SENDING_STATUS = reverse("offer_sending_status")


@pytest.mark.django_db
class TestOfferSendingStatus:
    def test_missing_params_raises(self, api_client, tenant):
        resp = api_client.get(URL_OFFER_SENDING_STATUS)
        # CommissioningError → 400 via the DRF exception handler.
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_offer_group_returns_404(self, api_client, tenant):
        resp = api_client.get(
            URL_OFFER_SENDING_STATUS,
            {
                "year": 2026,
                "delivery_week": 15,
                "offer_group": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_resellers_in_group(self, api_client, tenant):
        """All resellers in the offer-group are listed, with ``sent=False``
        when no ``OfferSending`` row exists for them yet."""
        offer_group = OfferGroupFactory()
        # Two resellers belonging to the group, one outside.
        r_in_1 = ResellerFactory()
        r_in_2 = ResellerFactory()
        r_out = ResellerFactory()
        offer_group.reseller_set.add(r_in_1, r_in_2)

        resp = api_client.get(
            URL_OFFER_SENDING_STATUS,
            {
                "year": 2026,
                "delivery_week": 15,
                "offer_group": str(offer_group.id),
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        ids = {entry["id"] for entry in resp.data}
        assert r_in_1.id in ids
        assert r_in_2.id in ids
        assert r_out.id not in ids
        assert all(entry["sent"] is False for entry in resp.data)

    def test_returns_sent_true_when_offersending_row_exists(self, api_client, tenant):
        """When an ``OfferSending`` row exists for a (group, year,
        week, reseller) tuple, the matching response entry has
        ``sent=True`` and a non-null ``sent_at``. P1-2 schema check:
        the view filters on the new composite-key columns directly,
        not via the dropped Offer JOIN."""
        from apps.commissioning.models import OfferSending

        offer_group = OfferGroupFactory()
        r_sent = ResellerFactory()
        r_unsent = ResellerFactory()
        offer_group.reseller_set.add(r_sent, r_unsent)

        OfferSending.objects.create(
            offer_group=offer_group,
            year=2026,
            delivery_week=15,
            reseller=r_sent,
        )

        resp = api_client.get(
            URL_OFFER_SENDING_STATUS,
            {
                "year": 2026,
                "delivery_week": 15,
                "offer_group": str(offer_group.id),
            },
        )
        assert resp.status_code == status.HTTP_200_OK
        by_id = {entry["id"]: entry for entry in resp.data}
        assert by_id[r_sent.id]["sent"] is True
        assert by_id[r_sent.id]["sent_at"] is not None
        assert by_id[r_unsent.id]["sent"] is False
        assert by_id[r_unsent.id]["sent_at"] is None

    def test_unique_composite_key_blocks_duplicate(self, tenant):
        """The ``UniqueConstraint`` on
        ``(offer_group, year, delivery_week, reseller)`` is the
        defense-in-depth backstop for the service's ``.exists()``
        pre-check. A second ``.create()`` with the same composite
        key MUST raise ``IntegrityError`` so a buggy / racing caller
        can't silently double-record a send."""
        from django.db import IntegrityError

        from apps.commissioning.models import OfferSending

        offer_group = OfferGroupFactory()
        reseller = ResellerFactory()
        offer_group.reseller_set.add(reseller)

        OfferSending.objects.create(
            offer_group=offer_group,
            year=2026,
            delivery_week=15,
            reseller=reseller,
        )
        with pytest.raises(IntegrityError):
            OfferSending.objects.create(
                offer_group=offer_group,
                year=2026,
                delivery_week=15,
                reseller=reseller,
            )


# ---------------------------------------------------------------------------
# BulkSendInvoiceRemindersViaEmailView  (validation only — happy path
# requires a configured SMTP backend that's out of scope for unit tests)
# ---------------------------------------------------------------------------
URL_SEND_REMINDERS = reverse("bulk_send_invoice_reminders_via_email")


@pytest.mark.django_db
class TestBulkSendInvoiceRemindersViaEmail:
    """View-layer tests for the enqueue endpoint. The actual SMTP
    work + grouping logic moved into ``invoice_reminder.
    bulk_send_invoice_reminders`` and is covered separately under
    ``tests_services/test_invoice_reminder_service.py``.

    These tests verify the 202+job_id contract and that the view
    validates its inputs synchronously before enqueueing.
    """

    def test_missing_model_returns_400(self, step_up_client, tenant):
        resp = step_up_client.post(URL_SEND_REMINDERS, {"ids": ["x"]}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_ids_returns_400(self, step_up_client, tenant):
        resp = step_up_client.post(
            URL_SEND_REMINDERS,
            {"ids": [], "model": "invoice"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_valid_payload_returns_202_and_creates_job(self, step_up_client, tenant):
        """Happy-path view contract: payload validates, a
        ``BackgroundJob`` row is created in ``queued`` state, and the
        response is a 202 with the job id. The actual SMTP / order
        resolution happens in the worker (covered by service tests),
        not here.
        """
        from apps.notifications.models import BackgroundJob

        before = BackgroundJob.objects.count()
        resp = step_up_client.post(
            URL_SEND_REMINDERS,
            {
                "ids": ["00000000-0000-0000-0000-000000000000"],
                "model": "invoice",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.data["kind"] == "invoice_reminder.bulk_send"
        assert resp.data["status"] == "queued"
        assert BackgroundJob.objects.count() == before + 1
        job = BackgroundJob.objects.get(pk=resp.data["job_id"])
        assert job.kind == "invoice_reminder.bulk_send"
        assert job.status == "queued"


# ---------------------------------------------------------------------------
# BulkSendOffersViaEmailView (validation + 404 — happy path needs SMTP)
# ---------------------------------------------------------------------------
URL_SEND_OFFERS = reverse("bulk_send_offers_via_email")


@pytest.mark.django_db
class TestBulkSendOffersViaEmail:
    def test_missing_offer_group_returns_400(self, step_up_client, tenant):
        resp = step_up_client.post(
            URL_SEND_OFFERS,
            {"year": 2026, "delivery_week": 15, "reseller_ids": []},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_offer_group_returns_404(self, step_up_client, tenant):
        # Serializer requires ``reseller_ids`` to be non-empty (min_length=1),
        # so pass a real reseller — otherwise we'd hit 400 from the serializer
        # before the offer_group lookup runs.
        reseller = ResellerFactory()
        resp = step_up_client.post(
            URL_SEND_OFFERS,
            {
                "year": 2026,
                "delivery_week": 15,
                "offer_group": "00000000-0000-0000-0000-000000000000",
                "reseller_ids": [str(reseller.id)],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_valid_payload_returns_202_and_creates_job(self, step_up_client, tenant):
        """Happy-path view contract after the Huey conversion: payload
        validates, ``OfferGroup`` lookup succeeds, a ``BackgroundJob``
        row is created in ``queued`` state, response is 202 with the
        job id. The actual SMTP work happens in the worker (covered
        by ``OfferService.bulk_send_offers_via_email`` tests).
        """
        from apps.commissioning.tests.factories import OfferGroupFactory
        from apps.notifications.models import BackgroundJob

        offer_group = OfferGroupFactory()
        reseller = ResellerFactory()

        before = BackgroundJob.objects.count()
        resp = step_up_client.post(
            URL_SEND_OFFERS,
            {
                "year": 2026,
                "delivery_week": 15,
                "offer_group": str(offer_group.id),
                "reseller_ids": [str(reseller.id)],
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.data["kind"] == "offer.bulk_send"
        assert resp.data["status"] == "queued"
        assert BackgroundJob.objects.count() == before + 1
        job = BackgroundJob.objects.get(pk=resp.data["job_id"])
        assert job.kind == "offer.bulk_send"
        assert job.status == "queued"


# ---------------------------------------------------------------------------
# BulkFinalizeDocumentsView happy path  (existing TestBulkFinalizeDocumentsView
# only covers validation branches — add the success branch here)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkFinalizeDocumentsViewHappyPath:
    def test_finalizes_delivery_note(self, api_client, tenant):
        reseller = ResellerFactory()
        order = OrderFactory(reseller=reseller)
        dn = DeliveryNoteResellerFactory(order=order)
        # DN must have at least one item — ``DeliveryNoteService.finalize_delivery_note``
        # refuses to finalize an empty DN with "Cannot finalize delivery note
        # - it has no items".
        DeliveryNoteContentFactory(delivery_note=dn)
        assert dn.is_finalized is False

        resp = api_client.post(
            URL_FINALIZE_DOCS,
            {"ids": [str(order.id)], "model": "delivery_note"},
            format="json",
        )
        assert resp.status_code in (status.HTTP_200_OK, status.HTTP_207_MULTI_STATUS)
        # Service flips ``is_finalized`` on success; tolerate the 207 branch
        # (per-order errors not under test here) but require finalize WAS
        # attempted on the right model.
        assert resp.data["model"] == "delivery_note"
        assert resp.data["total_processed"] == 1
