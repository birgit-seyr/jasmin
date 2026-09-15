"""Server-owned columns stay out of reach of the generic ModelViewSet writes.

Several ``fields = "__all__"`` serializers left columns that only services
may write (finalization stamps, GoBD source snapshots, parent-document FKs,
the frozen invoice recipient, authorship, renewal-chain identity, consent /
cancellation / waiting-list stamps) writable through a plain POST/PATCH.

DRF drops read-only keys silently, so every test sends the forged keys next
to one legitimate change and asserts: the request succeeds, the legitimate
change lands, and the server-owned columns are untouched. Existing clients
that echo whole rows back therefore keep working.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest import mock

import pytest
import time_machine
from django.urls import reverse
from rest_framework import status

from apps.commissioning.models import (
    DeliveryNoteContent,
    InvoiceResellerContent,
    ShareContent,
    ShareDelivery,
)
from apps.commissioning.tests.factories import (
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    DeliveryStationDayFactory,
    HarvestFactory,
    InvoiceResellerFactory,
    JasminUserFactory,
    MemberFactory,
    OfferFactory,
    OrderContentFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    StorageFactory,
    SubscriptionFactory,
    TheoreticalHarvestFactory,
)

FORGED_TIMESTAMP = "2020-01-01T00:00:00Z"
SOURCE_SNAPSHOT_FORGERY = {
    "source_amount": "99.000",
    "source_unit": "ST",
    "source_size": "L",
    "source_price_per_unit": "99.99",
    "source_rabatt": 50,
}


def _assert_source_snapshot_untouched(line) -> None:
    assert line.source_amount is None
    assert line.source_unit is None
    assert line.source_size is None
    assert line.source_price_per_unit is None
    assert line.source_rabatt is None


# ---------------------------------------------------------------------------
# Invoice lines
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInvoiceLineLocks:
    def _draft_line(self, invoice) -> InvoiceResellerContent:
        return InvoiceResellerContent.objects.create(
            invoice=invoice,
            share_article=ShareArticleFactory(),
            amount=Decimal("2.000"),
            unit="KG",
            size="M",
            tax_rate=Decimal("7.00"),
        )

    def test_patch_cannot_move_a_draft_line_onto_a_finalized_invoice(
        self, api_client, tenant
    ):
        reseller = ResellerFactory()
        draft_invoice = InvoiceResellerFactory(reseller=reseller)
        finalized_invoice = InvoiceResellerFactory(reseller=reseller, is_finalized=True)
        line = self._draft_line(draft_invoice)

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {"invoice": finalized_invoice.pk, "note": "moved"},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.invoice_id == draft_invoice.pk
        assert line.note == "moved"
        assert not finalized_invoice.items.exists()

    def test_patch_cannot_write_finalization_snapshot_or_provenance(
        self, api_client, tenant, user
    ):
        line = self._draft_line(InvoiceResellerFactory())
        delivery_note_line = DeliveryNoteContentFactory()

        resp = api_client.patch(
            reverse("invoice_contents-detail", kwargs={"pk": line.pk}),
            {
                "is_finalized": True,
                "finalized_at": FORGED_TIMESTAMP,
                "finalized_by": user.pk,
                **SOURCE_SNAPSHOT_FORGERY,
                "order_content": OrderContentFactory().pk,
                "delivery_note_contents": [delivery_note_line.pk],
                "note": "edited",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "edited"
        assert line.is_finalized is False
        assert line.finalized_at is None
        assert line.finalized_by_id is None
        _assert_source_snapshot_untouched(line)
        assert line.order_content_id is None
        assert not line.delivery_note_contents.exists()

    def test_create_still_takes_the_parent_invoice_but_no_server_owned_columns(
        self, api_client, tenant
    ):
        draft_invoice = InvoiceResellerFactory()

        resp = api_client.post(
            reverse("invoice_contents-list"),
            {
                "invoice": draft_invoice.pk,
                "share_article": ShareArticleFactory().pk,
                "amount": "1.000",
                "unit": "KG",
                "size": "M",
                "tax_rate": "7.00",
                "is_finalized": True,
                **SOURCE_SNAPSHOT_FORGERY,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        line = InvoiceResellerContent.objects.get(pk=resp.data["id"])
        assert line.invoice_id == draft_invoice.pk
        assert line.is_finalized is False
        _assert_source_snapshot_untouched(line)


# ---------------------------------------------------------------------------
# Delivery-note lines
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeliveryNoteLineLocks:
    def test_patch_cannot_move_a_line_or_write_server_owned_columns(
        self, api_client, tenant, user
    ):
        draft_delivery_note = DeliveryNoteResellerFactory()
        finalized_delivery_note = DeliveryNoteResellerFactory(is_finalized=True)
        line = DeliveryNoteContentFactory(delivery_note=draft_delivery_note)

        resp = api_client.patch(
            reverse("delivery_note_contents-detail", kwargs={"pk": line.pk}),
            {
                "delivery_note": finalized_delivery_note.pk,
                "is_finalized": True,
                "finalized_at": FORGED_TIMESTAMP,
                "finalized_by": user.pk,
                **SOURCE_SNAPSHOT_FORGERY,
                "order_content": OrderContentFactory().pk,
                "note": "edited",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        line.refresh_from_db()
        assert line.note == "edited"
        assert line.delivery_note_id == draft_delivery_note.pk
        assert line.is_finalized is False
        assert line.finalized_at is None
        assert line.finalized_by_id is None
        _assert_source_snapshot_untouched(line)
        assert line.order_content_id is None
        assert not finalized_delivery_note.items.exists()

    def test_create_still_takes_the_parent_delivery_note(self, api_client, tenant):
        draft_delivery_note = DeliveryNoteResellerFactory()

        resp = api_client.post(
            reverse("delivery_note_contents-list"),
            {
                "delivery_note": draft_delivery_note.pk,
                "share_article": ShareArticleFactory().pk,
                "amount": "1.000",
                "unit": "KG",
                "size": "M",
                "tax_rate": "7.00",
                "is_finalized": True,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        line = DeliveryNoteContent.objects.get(pk=resp.data["id"])
        assert line.delivery_note_id == draft_delivery_note.pk
        assert line.is_finalized is False


# ---------------------------------------------------------------------------
# Offers and the invoice document
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOfferLocks:
    def test_patch_cannot_finalize_an_offer(self, api_client, tenant, user):
        offer = OfferFactory()

        resp = api_client.patch(
            reverse("offer-detail", kwargs={"pk": offer.pk}),
            {
                "is_finalized": True,
                "finalized_at": FORGED_TIMESTAMP,
                "finalized_by": user.pk,
                "note": "edited",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        offer.refresh_from_db()
        assert offer.note == "edited"
        assert offer.is_finalized is False
        assert offer.finalized_at is None
        assert offer.finalized_by_id is None


@pytest.mark.django_db
class TestInvoiceRecipientSnapshotLock:
    def test_patch_cannot_plant_a_recipient_snapshot_on_a_draft(
        self, api_client, tenant
    ):
        invoice = InvoiceResellerFactory()
        assert invoice.recipient_snapshot is None
        original_hash_version = invoice.document_hash_version

        resp = api_client.patch(
            reverse("invoices-detail", kwargs={"pk": invoice.pk}),
            {
                "recipient_snapshot": {"name": "Forged Recipient GmbH"},
                "document_hash_version": original_hash_version + 5,
                "note": "edited",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        invoice.refresh_from_db()
        assert invoice.note == "edited"
        assert invoice.recipient_snapshot is None
        assert invoice.document_hash_version == original_hash_version


# ---------------------------------------------------------------------------
# Share contents
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShareContentLocks:
    def test_patch_cannot_unfinalize_or_rewrite_authorship(self, api_client, tenant):
        share_content = ShareContentFactory(is_finalized=True)
        original_created_at = share_content.created_at
        other_user = JasminUserFactory()

        with mock.patch("apps.commissioning.services.recompute.recompute_shares"):
            resp = api_client.patch(
                reverse("share_contents-detail", kwargs={"pk": share_content.pk}),
                {
                    "is_finalized": False,
                    "finalized_at": None,
                    "created_by": other_user.pk,
                    "created_at": FORGED_TIMESTAMP,
                    "note": "edited",
                },
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        share_content.refresh_from_db()
        assert share_content.note == "edited"
        assert share_content.is_finalized is True
        assert share_content.created_by_id is None
        assert share_content.created_at == original_created_at

    def test_create_stamps_the_request_user_as_author(self, api_client, tenant, user):
        share = ShareFactory()
        station_day = DeliveryStationDayFactory(delivery_day=share.delivery_day)

        with mock.patch("apps.commissioning.services.recompute.recompute_shares"):
            resp = api_client.post(
                reverse("share_contents-list"),
                {
                    "share": share.pk,
                    "share_article": ShareArticleFactory().pk,
                    "delivery_station": station_day.delivery_station_id,
                    "amount": "5.000",
                    "unit": "KG",
                    "size": "M",
                    "created_by": JasminUserFactory().pk,
                    "is_finalized": True,
                },
                format="json",
            )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        share_content = ShareContent.objects.get(pk=resp.data["id"])
        assert share_content.created_by_id == user.pk
        assert share_content.is_finalized is False


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDocumentationLocks:
    def test_harvest_patch_cannot_finalize_or_rewrite_authorship(
        self, api_client, tenant, user
    ):
        harvest = HarvestFactory(amount=Decimal("4.00"))
        original_created_at = harvest.created_at

        resp = api_client.patch(
            reverse("harvest-detail", kwargs={"pk": harvest.pk}),
            {
                "is_finalized": True,
                "finalized_at": FORGED_TIMESTAMP,
                "finalized_by": user.pk,
                "created_by": JasminUserFactory().pk,
                "created_at": FORGED_TIMESTAMP,
                "note": "edited",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        harvest.refresh_from_db()
        assert harvest.note == "edited"
        assert harvest.is_finalized is False
        assert harvest.finalized_at is None
        assert harvest.finalized_by_id is None
        assert harvest.created_by_id is None
        assert harvest.created_at == original_created_at

    def test_harvest_create_stamps_the_request_user_as_author(
        self, api_client, tenant, user
    ):
        from apps.commissioning.models import Harvest

        storage = StorageFactory(is_short_term_harvest_storage=True)

        resp = api_client.post(
            reverse("harvest-list"),
            {
                "year": 2026,
                "delivery_week": 15,
                "day_number": 1,
                "share_article": ShareArticleFactory().pk,
                "amount": "3.00",
                "unit": "KG",
                "size": "M",
                "storage": storage.pk,
                "created_by": JasminUserFactory().pk,
                "is_finalized": True,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        harvest = Harvest.objects.get()
        assert harvest.created_by_id == user.pk
        assert harvest.is_finalized is False

    def test_theoretical_harvest_patch_cannot_rewrite_authorship(
        self, api_client, tenant
    ):
        # The theoretical list/detail queryset is scoped to the recent weeks
        # around "now"; pin the clock inside the factory's week 15/2026.
        with time_machine.travel(datetime.datetime(2026, 4, 13, 12, 0), tick=False):
            theoretical_harvest = TheoreticalHarvestFactory()
            original_created_at = theoretical_harvest.created_at

            resp = api_client.patch(
                reverse(
                    "theoretical_harvests-detail",
                    kwargs={"pk": theoretical_harvest.pk},
                ),
                {
                    "created_by": JasminUserFactory().pk,
                    "created_at": FORGED_TIMESTAMP,
                    "note": "edited",
                },
                format="json",
            )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        theoretical_harvest.refresh_from_db()
        assert theoretical_harvest.note == "edited"
        assert theoretical_harvest.created_by_id is None
        assert theoretical_harvest.created_at == original_created_at


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSubscriptionLocks:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        # Before the factory term (2026-01-05 → 2027-01-03) so no
        # past/lead-time guard can flip.
        with time_machine.travel(datetime.datetime(2025, 11, 3, 12, 0), tick=False):
            yield

    def test_patch_cannot_rewrite_renewal_chain_or_audit_stamps(
        self, api_client, tenant
    ):
        draft = SubscriptionFactory(admin_confirmed=False, quantity=1)
        # Reuse the draft's station-day + variation: a second factory chain would
        # open another day_number=2 SharesDeliveryDay (one open per day number).
        other_member_subscription = SubscriptionFactory(
            admin_confirmed=False,
            share_type_variation=draft.share_type_variation,
            default_delivery_station_day=draft.default_delivery_station_day,
        )
        original_number = draft.subscription_number
        original_created_at = draft.created_at

        resp = api_client.patch(
            reverse("abos-detail", kwargs={"pk": draft.pk}),
            {
                "subscription_number": other_member_subscription.subscription_number,
                "renewal_generation": 4,
                "previous_subscription": other_member_subscription.pk,
                "created_by": JasminUserFactory().pk,
                "created_at": FORGED_TIMESTAMP,
                "waiting_list_status": "confirmed",
                "quantity": 2,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        draft.refresh_from_db()
        assert draft.quantity == 2
        assert draft.subscription_number == original_number
        assert draft.renewal_generation == 0
        assert draft.previous_subscription_id is None
        assert draft.created_by_id is None
        assert draft.created_at == original_created_at
        assert draft.waiting_list_status == "not_on_list"


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberLocks:
    STAMP_FIELDS = (
        "consent_withdrawn_at",
        "cancellation_email_sent_at",
        "notification_sent_at",
        "notification_expires_at",
        "response_received_at",
    )

    def test_patch_cannot_write_consent_cancellation_waiting_list_or_audit(
        self, api_client, tenant
    ):
        member = MemberFactory()
        original_created_at = member.created_at

        resp = api_client.patch(
            reverse("member-detail", kwargs={"pk": member.pk}),
            {
                **{field: FORGED_TIMESTAMP for field in self.STAMP_FIELDS},
                "waiting_list_status": "spot_available",
                "created_by": JasminUserFactory().pk,
                "created_at": FORGED_TIMESTAMP,
                "note": "edited",
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        member.refresh_from_db()
        assert member.note == "edited"
        for field in self.STAMP_FIELDS:
            assert getattr(member, field) is None, field
        assert member.waiting_list_status == "not_on_list"
        assert member.created_by_id is None
        assert member.created_at == original_created_at

    def test_create_stamps_the_request_user_as_author(self, api_client, tenant, user):
        from apps.commissioning.models import Member

        resp = api_client.post(
            reverse("member-list"),
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada.lovelace.lock-test@example.com",
                "created_by": JasminUserFactory().pk,
                "consent_withdrawn_at": FORGED_TIMESTAMP,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        member = Member.objects.get(email="ada.lovelace.lock-test@example.com")
        assert member.created_by_id == user.pk
        assert member.consent_withdrawn_at is None


# ---------------------------------------------------------------------------
# Share deliveries
# ---------------------------------------------------------------------------
def _delivery_slot():
    """A share + station-day on one delivery day and a matching subscription.

    ONE SharesDeliveryDay for the whole chain — two factory chains would each
    open a day_number=2 row and trip ``sharesdeliveryday_one_open_per_day_number``.
    """
    day = SharesDeliveryDayFactory()
    station_day = DeliveryStationDayFactory(delivery_day=day)
    variation = ShareTypeVariationFactory()
    share = ShareFactory(delivery_day=day, share_type_variation=variation)
    subscription = SubscriptionFactory(
        share_type_variation=variation, default_delivery_station_day=station_day
    )
    return share, station_day, subscription


@pytest.fixture()
def _no_write_side_effects():
    # Billing re-plan + planning rebuild are covered elsewhere; these tests are
    # about which columns the serializer lets through.
    with (
        mock.patch("apps.shared.subscription_hooks.notify_subscription_changed"),
        mock.patch("apps.commissioning.services.recompute.recompute_shares"),
    ):
        yield


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_write_side_effects")
class TestShareDeliveryLocks:
    def test_overview_create_ignores_the_display_annotations(self, api_client, tenant):
        share, station_day, subscription = _delivery_slot()

        resp = api_client.post(
            reverse("share_delivery_overview-list"),
            {
                "share": share.pk,
                "subscription": subscription.pk,
                "delivery_station_day": station_day.pk,
                "joker_taken": False,
                # Echoed display columns of the grid row.
                "quantity": 5,
                "share_type_variation_string": "Harvest share - M",
                "delivery_week": share.delivery_week,
            },
            format="json",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert ShareDelivery.objects.filter(
            share=share, subscription=subscription, delivery_station_day=station_day
        ).exists()

    @pytest.mark.parametrize(
        "url_name", ["share_delivery-detail", "share_delivery_overview-detail"]
    )
    def test_patch_cannot_repoint_a_delivery_to_another_subscription(
        self, api_client, tenant, url_name
    ):
        share, station_day, subscription = _delivery_slot()
        delivery = ShareDelivery.objects.create(
            share=share, subscription=subscription, delivery_station_day=station_day
        )
        other_subscription = SubscriptionFactory(
            share_type_variation=share.share_type_variation,
            default_delivery_station_day=station_day,
        )

        resp = api_client.patch(
            reverse(url_name, kwargs={"pk": delivery.pk}),
            {"subscription": other_subscription.pk, "joker_taken": True},
            format="json",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.data
        delivery.refresh_from_db()
        assert delivery.joker_taken is True
        assert delivery.subscription_id == subscription.pk
