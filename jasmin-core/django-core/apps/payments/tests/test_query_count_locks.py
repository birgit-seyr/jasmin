"""Performance regression locks for hot list endpoints.

These tests don't measure wall-clock latency — they assert that adding
more rows to a list endpoint does **not** add proportional queries. That
is the canonical N+1 detection pattern: run the same endpoint with
N=small and N=larger, and assert the query count is identical (or within
a tiny constant). When this test fails, someone removed a
``select_related`` / ``prefetch_related`` somewhere upstream.


"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import (
    CrateFactory,
    DeliveryNoteContentFactory,
    DeliveryNoteResellerFactory,
    DeliveryStationDayFactory,
    DeliveryStationFactory,
    InvoiceResellerFactory,
    JasminUserFactory,
    MemberFactory,
    OrderContentFactory,
    OrderFactory,
    PaymentCycleFactory,
    ResellerFactory,
    ShareArticleFactory,
    ShareContentFactory,
    ShareDeliveryFactory,
    ShareFactory,
    SharesDeliveryDayFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)

pytestmark = pytest.mark.django_db


# Generous absolute ceiling that still catches obvious regressions.
HARD_CEILING = 80


def _count_queries_on(client: APIClient, url: str) -> int:
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url)
    assert resp.status_code in (200, 204), (
        f"{url} returned {resp.status_code}; perf-lock test cannot validate "
        f"a failing endpoint. Body: {resp.content[:200]!r}"
    )
    return len(ctx.captured_queries)


@pytest.fixture()
def office_client(tenant):
    user = JasminUserFactory(roles=["office", "admin"])
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture()
def shared_station_day(tenant):
    """One shared SharesDeliveryDay + DeliveryStationDay across all
    subscriptions in this test. SharesDeliveryDay enforces
    ``overlap_unique_fields=("day_number",)``, so SubscriptionFactory's
    default SubFactory chain would clash on the second call."""
    day = SharesDeliveryDayFactory()
    return DeliveryStationDayFactory(delivery_day=day)


def _make_subscription(station_day):
    member = MemberFactory()
    return SubscriptionFactory(
        member=member,
        default_delivery_station_day=station_day,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
    )


# --------------------------------------------------------------------------- #
# /api/commissioning/members/                                                 #
# --------------------------------------------------------------------------- #


def test_members_list_is_scale_invariant(tenant, office_client):
    for _ in range(2):
        MemberFactory()
    small = _count_queries_on(office_client, "/api/commissioning/members/")

    for _ in range(8):
        MemberFactory()
    large = _count_queries_on(office_client, "/api/commissioning/members/")

    assert large - small <= 3, (
        f"members/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"members/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/abos/                                                    #
# --------------------------------------------------------------------------- #


def test_abos_list_is_scale_invariant(tenant, office_client, shared_station_day):
    for _ in range(2):
        _make_subscription(shared_station_day)
    small = _count_queries_on(office_client, "/api/commissioning/abos/")

    for _ in range(6):
        _make_subscription(shared_station_day)
    large = _count_queries_on(office_client, "/api/commissioning/abos/")

    assert large - small <= 3, (
        f"abos/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"abos/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/payments/charge_schedules/                                              #
# --------------------------------------------------------------------------- #


def test_charge_schedules_list_is_scale_invariant(
    tenant, office_client, tenant_settings, shared_station_day
):
    """ChargeSchedule rows are produced by ``regenerate_for_subscription``.
    A single subscription generates ~12 monthly rows — plenty for an N+1
    on subscription/member joins to surface. We compare 1 sub vs 2 subs."""
    from apps.payments.services import ChargeScheduleService

    sub = _make_subscription(shared_station_day)
    ChargeScheduleService.regenerate_for_subscription(sub)

    first = _count_queries_on(office_client, "/api/payments/charge_schedules/")

    sub2 = _make_subscription(shared_station_day)
    ChargeScheduleService.regenerate_for_subscription(sub2)
    second = _count_queries_on(office_client, "/api/payments/charge_schedules/")

    assert second - first <= 3, (
        f"charge_schedules/ N+1 suspected: 1 sub -> {first} queries, "
        f"2 subs -> {second} queries (delta {second - first})."
    )
    assert second <= HARD_CEILING, f"charge_schedules/ exceeded hard ceiling: {second}"


# --------------------------------------------------------------------------- #
# /api/commissioning/share_delivery/                                          #
# --------------------------------------------------------------------------- #


def _make_share_delivery(station_day, share_type_variation, *, delivery_week):
    """Create one ShareDelivery with a real subscription chain attached.

    The serializer dereferences the full
    ``subscription -> share_type_variation -> share_type``
    chain and ``share -> delivery_day``, so we MUST attach a subscription
    (factory default leaves it null) for the perf surface to be exercised.

    ``delivery_week`` must be unique per call: Share has a unique
    constraint on ``(year, delivery_week, delivery_day, share_type_variation)``.
    """
    member = MemberFactory()
    sub = SubscriptionFactory(
        member=member,
        share_type_variation=share_type_variation,
        default_delivery_station_day=station_day,
        valid_from=datetime.date(2026, 1, 5),
        valid_until=datetime.date(2026, 12, 27),
        quantity=1,
        price_per_delivery=Decimal("10.00"),
        payment_cycle=PaymentCycleFactory(choice="MONTHLY"),
    )
    share = ShareFactory(
        delivery_day=station_day.delivery_day,
        share_type_variation=share_type_variation,
        delivery_week=delivery_week,
    )
    # A ShareContent with a non-null seller (distinct Reseller per row)
    # exercises the serializer's ``seller.name_for_member_pages`` deref — the
    # surface the ``share__sharecontent_set__seller`` prefetch protects.
    # Without it the factory leaves ShareContent.seller null and the lock
    # can't catch a per-row seller fetch.
    ShareContentFactory(share=share, seller=ResellerFactory())
    return ShareDeliveryFactory(
        subscription=sub, share=share, delivery_station_day=station_day
    )


def test_share_delivery_list_is_scale_invariant(
    tenant, office_client, shared_station_day
):
    """ShareDeliveryViewSet already has a thorough select_related/
    prefetch_related chain. This test locks that in: a regression that
    drops one of those joins would show up as +N queries per row."""
    stv = ShareTypeVariationFactory()

    week = 1
    for _ in range(2):
        _make_share_delivery(shared_station_day, stv, delivery_week=week)
        week += 1
    small = _count_queries_on(
        office_client, "/api/commissioning/share_delivery/?year=2026"
    )

    for _ in range(6):
        _make_share_delivery(shared_station_day, stv, delivery_week=week)
        week += 1
    large = _count_queries_on(
        office_client, "/api/commissioning/share_delivery/?year=2026"
    )

    assert large - small <= 3, (
        f"share_delivery/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"share_delivery/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/invoices/                                                #
# --------------------------------------------------------------------------- #


def _make_invoice_with_line_and_crate(*, reseller, year, delivery_week):
    """Create one InvoiceReseller with a single line item and a single crate
    item attached. Exercises the serializer's full per-row chain:
    ``reseller__contact``, ``items`` (line_items), ``crate_items``,
    ``created_by``.

    ``delivery_week`` is varied per call so the Order's
    ``(reseller, year, week, day)`` uniqueness isn't tripped when seeding
    multiple rows for the same reseller.
    """
    from apps.commissioning.models import (
        CrateContentInvoiceReseller,
        InvoiceResellerContent,
    )

    order = OrderFactory(
        reseller=reseller, year=year, delivery_week=delivery_week, day_number=2
    )
    OrderContentFactory(order=order)
    invoice = InvoiceResellerFactory(reseller=reseller)
    InvoiceResellerContent.objects.create(
        invoice=invoice,
        share_article=ShareArticleFactory(),
        amount=Decimal("10.000"),
        price_per_unit=Decimal("1.50"),
        unit="KG",
        size="M",
        tax_rate=Decimal("7.00"),
    )
    CrateContentInvoiceReseller.objects.create(
        invoice=invoice,
        crate_type=CrateFactory(),
        amount=2,
        price_per_unit=Decimal("0.50"),
        tax_rate=Decimal("19.00"),
    )
    return invoice


def test_invoices_list_is_scale_invariant(tenant, office_client):
    """InvoiceResellerViewSet's prefetch chain — including the Python-side
    aggregation in ``InvoiceResellerSerializer.get_crate_items`` — must
    not produce per-row queries. Regression here means someone either
    removed a ``select_related`` / ``prefetch_related`` or restored the
    fresh ``CrateContentInvoiceReseller.objects.filter(invoice=obj)``
    pattern that the 2026-05-24 audit replaced."""
    reseller = ResellerFactory()

    week = 10
    for _ in range(2):
        _make_invoice_with_line_and_crate(
            reseller=reseller, year=2026, delivery_week=week
        )
        week += 1
    small = _count_queries_on(office_client, "/api/commissioning/invoices/")

    for _ in range(6):
        _make_invoice_with_line_and_crate(
            reseller=reseller, year=2026, delivery_week=week
        )
        week += 1
    large = _count_queries_on(office_client, "/api/commissioning/invoices/")

    assert large - small <= 3, (
        f"invoices/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"invoices/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/delivery_notes/                                          #
# --------------------------------------------------------------------------- #


def _make_delivery_note_with_line_and_crate(*, reseller, year, delivery_week):
    """Create one DeliveryNoteReseller with a single line item and a single
    crate item attached. Same purpose as ``_make_invoice_with_line_and_crate``
    above — exercise the full serializer chain so the perf lock catches a
    dropped prefetch."""
    from apps.commissioning.models import CrateDeliveryNoteContent

    order = OrderFactory(
        reseller=reseller, year=year, delivery_week=delivery_week, day_number=2
    )
    delivery_note = DeliveryNoteResellerFactory(order=order)
    DeliveryNoteContentFactory(delivery_note=delivery_note)
    CrateDeliveryNoteContent.objects.create(
        delivery_note=delivery_note,
        crate_type=CrateFactory(),
        amount=2,
        price_per_unit=Decimal("0.50"),
        tax_rate=Decimal("19.00"),
    )
    return delivery_note


def test_delivery_notes_list_is_scale_invariant(tenant, office_client):
    """DeliveryNoteResellerViewSet — same lock as invoices/, same chain."""
    reseller = ResellerFactory()

    week = 20
    for _ in range(2):
        _make_delivery_note_with_line_and_crate(
            reseller=reseller, year=2026, delivery_week=week
        )
        week += 1
    small = _count_queries_on(office_client, "/api/commissioning/delivery_notes/")

    for _ in range(6):
        _make_delivery_note_with_line_and_crate(
            reseller=reseller, year=2026, delivery_week=week
        )
        week += 1
    large = _count_queries_on(office_client, "/api/commissioning/delivery_notes/")

    assert large - small <= 3, (
        f"delivery_notes/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"delivery_notes/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/commissioning_lists_resellers/                           #
# --------------------------------------------------------------------------- #


def test_commissioning_list_is_scale_invariant(tenant, office_client):
    """The orders-overview aggregation already prefetches
    ``reseller__contact`` and ``ordercontent_set__{share_article, offer__share_article}``
    (see ``CommissioningListResellersViewSet.list`` at
    apps/commissioning/viewsets/resellers_viewsets.py). Lock that chain
    so a future contributor dropping one of those joins is loud.

    The endpoint requires ``year``, ``delivery_week``, ``day_number`` —
    all seeded rows must match for them to show up."""
    year, week, day = 2026, 30, 2
    url = (
        "/api/commissioning/commissioning_lists_resellers/"
        f"?year={year}&delivery_week={week}&day_number={day}"
    )

    # Each seeded order belongs to its own reseller so the response
    # grows row-by-row (one entry per reseller per day).
    def _seed_one_order():
        reseller = ResellerFactory()
        order = OrderFactory(
            reseller=reseller, year=year, delivery_week=week, day_number=day
        )
        OrderContentFactory(order=order)
        return order

    for _ in range(2):
        _seed_one_order()
    small = _count_queries_on(office_client, url)

    for _ in range(6):
        _seed_one_order()
    large = _count_queries_on(office_client, url)

    assert large - small <= 3, (
        f"commissioning_lists_resellers/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert (
        large <= HARD_CEILING
    ), f"commissioning_lists_resellers/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/resellers/                                               #
# --------------------------------------------------------------------------- #


def test_resellers_list_is_scale_invariant(tenant, office_client):
    """ResellerViewSet does ``select_related("contact")`` and the
    serializer dereferences the contact on every row. Lock that join."""
    for _ in range(2):
        ResellerFactory()
    small = _count_queries_on(office_client, "/api/commissioning/resellers/")

    for _ in range(8):
        ResellerFactory()
    large = _count_queries_on(office_client, "/api/commissioning/resellers/")

    assert large - small <= 3, (
        f"resellers/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"resellers/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/consents/                                                #
# --------------------------------------------------------------------------- #


def _make_consent_record(document):
    from apps.commissioning.models import ConsentRecord

    return ConsentRecord.objects.create(member=MemberFactory(), document=document)


def test_consents_list_is_scale_invariant(tenant, office_client):
    """ConsentRecordViewSet does ``select_related("document", "member")``;
    the serializer renders both sides. One shared document, one member per
    record — the member join is the N+1 surface."""
    from apps.commissioning.models import ConsentDocument

    document = ConsentDocument.objects.create(
        kind="privacy",
        version="2026-01-05",
        locale="de",
        title="Privacy policy",
        body="Privacy policy body for perf-lock test.",
        valid_from=datetime.date(2026, 1, 5),
    )

    for _ in range(2):
        _make_consent_record(document)
    small = _count_queries_on(office_client, "/api/commissioning/consents/")

    for _ in range(8):
        _make_consent_record(document)
    large = _count_queries_on(office_client, "/api/commissioning/consents/")

    assert large - small <= 3, (
        f"consents/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"consents/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/payments/billing_profiles/                                             #
# --------------------------------------------------------------------------- #


def _make_billing_profile():
    from apps.payments.models import BillingProfile, PaymentMethodOptions

    member = MemberFactory()
    return BillingProfile.objects.create(
        member=member,
        payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
        iban="DE89370400440532013000",
        account_holder=f"{member.first_name} {member.last_name}",
        sepa_mandate_reference=f"MND-{member.pk}",
        sepa_mandate_signed_at=datetime.date(2026, 1, 1),
        is_active=True,
    )


def test_billing_profiles_list_is_scale_invariant(tenant, office_client):
    """BillingProfileViewSet — flat serializer today (member rendered as
    pk), but the rows carry encrypted SEPA columns and the PII-read
    logging mixin. Lock the baseline so a future ``member.<attr>``
    serializer field without a ``select_related`` is loud."""
    for _ in range(2):
        _make_billing_profile()
    small = _count_queries_on(office_client, "/api/payments/billing_profiles/")

    for _ in range(8):
        _make_billing_profile()
    large = _count_queries_on(office_client, "/api/payments/billing_profiles/")

    assert large - small <= 3, (
        f"billing_profiles/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"billing_profiles/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/notifications/email-logs/                                              #
# --------------------------------------------------------------------------- #


def test_email_logs_list_is_scale_invariant(tenant, office_client):
    """EmailLogViewSet — flat model with no FKs today. Lock the baseline
    so a future relation (template FK, member FK for GDPR linkage)
    added without a ``select_related`` is loud."""
    from apps.notifications.models import EmailLog

    def _seed(n: int) -> None:
        for i in range(n):
            EmailLog.objects.create(
                recipient=f"perf-lock-{i}@example.com",
                subject="perf-lock",
                purpose="test",
                status="sent",
            )

    _seed(2)
    small = _count_queries_on(office_client, "/api/notifications/email-logs/")

    _seed(8)
    large = _count_queries_on(office_client, "/api/notifications/email-logs/")

    assert large - small <= 3, (
        f"email-logs/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"email-logs/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/orders_overview/  (PERF-1)                                #
# --------------------------------------------------------------------------- #


def _make_order_with_invoiced_delivery_note(*, reseller, year, delivery_week):
    """Order with a delivery note AND a linked invoice (via the
    ``InvoiceResellerContent.delivery_note_contents`` M2M) plus line items, so
    ``CombinedOrderOverviewView``'s batched invoice lookup + ``sum_netto`` are
    both exercised. Pre-fix this ran a per-order invoice query (+ a
    ``cancelled_by_invoice`` fetch) per row."""
    from apps.commissioning.models import InvoiceResellerContent

    order = OrderFactory(
        reseller=reseller, year=year, delivery_week=delivery_week, day_number=2
    )
    delivery_note = DeliveryNoteResellerFactory(order=order)
    dnc = DeliveryNoteContentFactory(delivery_note=delivery_note)
    invoice = InvoiceResellerFactory(reseller=reseller)
    irc = InvoiceResellerContent.objects.create(
        invoice=invoice,
        share_article=ShareArticleFactory(),
        amount=Decimal("10.000"),
        price_per_unit=Decimal("1.50"),
        unit="KG",
        size="M",
        tax_rate=Decimal("7.00"),
    )
    irc.delivery_note_contents.add(dnc)
    return order


def test_orders_overview_is_scale_invariant(tenant, office_client):
    """CombinedOrderOverviewView resolves each order's invoice and computes
    ``sum_netto``. The per-order invoice lookup must be batched (PERF-1) —
    adding orders must not add proportional queries."""
    reseller = ResellerFactory()

    week = 30
    for _ in range(2):
        _make_order_with_invoiced_delivery_note(
            reseller=reseller, year=2026, delivery_week=week
        )
        week += 1
    small = _count_queries_on(
        office_client, "/api/commissioning/orders_overview/?year=2026"
    )

    for _ in range(6):
        _make_order_with_invoiced_delivery_note(
            reseller=reseller, year=2026, delivery_week=week
        )
        week += 1
    large = _count_queries_on(
        office_client, "/api/commissioning/orders_overview/?year=2026"
    )

    assert large - small <= 3, (
        f"orders_overview/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"orders_overview/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/resellers/ WITH linked users  (PERF-2)                    #
# --------------------------------------------------------------------------- #
# The lock above seeds plain resellers (``linked_user=None``), which
# short-circuits ``get_linked_user_info`` — so it never caught the linked-user
# N+1. This one sets a linked user per row to exercise that path.


def test_resellers_list_with_linked_user_is_scale_invariant(tenant, office_client):
    """``ResellerSerializer.get_linked_user_info`` serializes the linked user
    per row — its sent-invitation lookup and the reverse ``linked_reseller``
    OneToOne must be prefetched (PERF-2). A linked user is set explicitly here
    or the path would short-circuit and the lock would catch nothing."""
    for _ in range(2):
        ResellerFactory(linked_user=JasminUserFactory())
    small = _count_queries_on(office_client, "/api/commissioning/resellers/")

    for _ in range(8):
        ResellerFactory(linked_user=JasminUserFactory())
    large = _count_queries_on(office_client, "/api/commissioning/resellers/")

    assert large - small <= 3, (
        f"resellers/ (linked user) N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert (
        large <= HARD_CEILING
    ), f"resellers/ (linked user) exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/resellers/ WITH linked delivery stations  (PERF-4)        #
# --------------------------------------------------------------------------- #
# The locks above seed resellers without a linked delivery station, so
# ``get_linked_delivery_station_can_be_deleted`` short-circuits (returns True)
# and never runs ``can_delete_instance``. This one links a delivery station per
# row to exercise that deletability check — it must be batched, not per-row.


def test_resellers_list_with_linked_delivery_station_is_scale_invariant(
    tenant, office_client
):
    """``get_linked_delivery_station_can_be_deleted`` ran ``can_delete_instance``
    (R queries) per row's linked DeliveryStation. ``ResellerListSerializer``
    bulk-precomputes it; a linked station is set per row or the field would
    short-circuit and the lock would catch nothing."""

    def _seed():
        reseller = ResellerFactory()
        DeliveryStationFactory(linked_reseller=reseller)

    for _ in range(2):
        _seed()
    small = _count_queries_on(office_client, "/api/commissioning/resellers/")

    for _ in range(8):
        _seed()
    large = _count_queries_on(office_client, "/api/commissioning/resellers/")

    assert large - small <= 3, (
        f"resellers/ (linked DS) N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert (
        large <= HARD_CEILING
    ), f"resellers/ (linked DS) exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/auth/admin/users/  (PERF-3)                                            #
# --------------------------------------------------------------------------- #
# AdminUserViewSet.list -> list_active_users serializes every user via
# serialize_user_row, which reads a sent-invitation lookup AND the reverse
# ``linked_reseller`` OneToOne per row. Both are N+1 without the Prefetch +
# select_related that the commissioning members/resellers viewsets already use
# for the SAME serializer. A reverse OneToOne that resolves to "no row" still
# fires a query per access, so even reseller-less users surface the regression.


def test_admin_users_list_is_scale_invariant(tenant, office_client):
    """``office_client`` carries the ``admin`` role, so it can hit the
    admin-only endpoint. Seed a mix of plain and reseller-linked users to
    exercise both the present and absent reverse-OneToOne paths."""
    for i in range(2):
        user = JasminUserFactory()
        if i % 2 == 0:
            ResellerFactory(linked_user=user)
    small = _count_queries_on(office_client, "/api/auth/admin/users/")

    for i in range(8):
        user = JasminUserFactory()
        if i % 2 == 0:
            ResellerFactory(linked_user=user)
    large = _count_queries_on(office_client, "/api/auth/admin/users/")

    assert large - small <= 3, (
        f"admin/users/ N+1 suspected: {small} queries small, "
        f"{large} queries large (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"admin/users/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/commissioning/offers/                                                  #
# --------------------------------------------------------------------------- #


def test_offers_list_is_scale_invariant(tenant, office_client):
    """OfferSerializer.organic_status reads ``share_article.organic_status`` per
    row, so OfferViewSet.get_queryset must ``select_related("share_article")`` or
    the offers list (one offer per article, often dozens) goes N+1 (NQ-1). The
    ``share_article_name`` F() annotation only pulls the name column via JOIN —
    it does NOT populate the related instance the serializer dereferences."""
    from apps.commissioning.tests.factories import OfferFactory, OfferGroupFactory

    group = OfferGroupFactory()
    url = "/api/commissioning/offers/?year=2026&delivery_week=15"

    for _ in range(2):
        OfferFactory(year=2026, delivery_week=15, offer_group=group)
    small = _count_queries_on(office_client, url)

    for _ in range(6):
        OfferFactory(year=2026, delivery_week=15, offer_group=group)
    large = _count_queries_on(office_client, url)

    assert large - small <= 3, (
        f"offers/ N+1 suspected: 2 rows -> {small} queries, "
        f"8 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"offers/ exceeded hard ceiling: {large}"


# --------------------------------------------------------------------------- #
# /api/payments/billing_runs/                                                 #
# --------------------------------------------------------------------------- #


def test_billing_runs_list_is_scale_invariant(tenant, office_client):
    """BillingRunViewSet — flat serializer today (created_by rendered as a pk,
    sepa_xml_export_url read off the same-row FileField). No live N+1; lock the
    baseline so a future ``created_by.<attr>`` serializer field added without a
    ``select_related`` is loud."""
    from apps.payments.models import BillingRun

    def _seed(n: int) -> None:
        for _ in range(n):
            BillingRun.objects.create(
                period_start=datetime.date(2026, 1, 1),
                period_end=datetime.date(2026, 1, 31),
                collection_date=datetime.date(2026, 2, 5),
            )

    _seed(2)
    small = _count_queries_on(office_client, "/api/payments/billing_runs/")

    _seed(8)
    large = _count_queries_on(office_client, "/api/payments/billing_runs/")

    assert large - small <= 3, (
        f"billing_runs/ N+1 suspected: 2 rows -> {small} queries, "
        f"10 rows -> {large} queries (delta {large - small})."
    )
    assert large <= HARD_CEILING, f"billing_runs/ exceeded hard ceiling: {large}"
