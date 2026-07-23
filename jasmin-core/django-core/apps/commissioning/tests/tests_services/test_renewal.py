"""Auto-renewal service — apps/commissioning/services/renewal.py.

A confirmed, non-trial subscription whose cancellation deadline has lapsed (and
that hasn't been renewed) gets an UNCONFIRMED draft renewal for the immediately
following term: same member / quantity / cycle / station-day, re-resolved price,
the same-size successor variation if its own has ended. A failure creates no
draft (the source stays renewable), is counted, and never aborts the run.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.commissioning.models import Member, Subscription
from apps.commissioning.services.renewal import (
    create_renewal_draft,
    resolve_variation_for_term,
    run_renewals,
)
from apps.commissioning.tests.factories import (
    DeliveryStationDayFactory,
    MemberFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
    ShareTypeVariationGrossPriceFactory,
    SubscriptionFactory,
)
from apps.shared.tenants.models import TenantSettings

_VALID_FROM = datetime.date(2026, 1, 5)  # Monday
_VALID_UNTIL = datetime.date(2026, 12, 27)  # Sunday — inside the renewal window
_TODAY = datetime.date(2026, 11, 30)  # within 6 weeks before _VALID_UNTIL
_MIN_WEEKS = 6


def _renewable_sub(**kwargs) -> Subscription:
    defaults = dict(
        admin_confirmed=True,
        is_trial=False,
        valid_from=_VALID_FROM,
        valid_until=_VALID_UNTIL,
        # A real subscription carries a price; without one the renewal now
        # refuses (BIZ-7: a None price would materialise a €0 term). Tests
        # exercising the None-price refusal override this explicitly.
        price_per_delivery=Decimal("10.00"),
    )
    defaults.update(kwargs)
    subscription = SubscriptionFactory(**defaults)
    # Real data always carries a reference price window (the API refuses
    # subscription creation without an active price), and the renewal price
    # now ONLY resolves from windows — never from the predecessor's stored
    # (possibly solidarity/custom) figure. Seed one for the factory-made
    # variation; tests that pass their own variation manage windows themselves.
    if "share_type_variation" not in kwargs:
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=subscription.share_type_variation,
            valid_from=_VALID_FROM,
            price_per_delivery=Decimal("10.00"),
        )
    return subscription


def _make_settings(tenant, **kwargs) -> TenantSettings:
    """Materialise a current TenantSettings row (overrides via kwargs)."""
    return TenantSettings.objects.create(
        tenant=tenant,
        valid_from=timezone.now() - datetime.timedelta(seconds=1),
        **kwargs,
    )


@pytest.mark.django_db
class TestRenewalTermAnchoring:
    """The renewal RE-ANCHORS its term end to the tenant's configured ISO week
    (so the yearly restart week doesn't drift across 52-/53-week ISO years),
    falling back to the predecessor's term length only when neither end rule is
    configured."""

    def test_reanchors_to_iso_week_for_end_after_one_year(self, tenant):
        _make_settings(
            tenant,
            subscriptions_end_after_one_year=True,
            subscriptions_end_at_end_of_season=False,
        )
        sub = _renewable_sub(
            valid_from=datetime.date(2026, 1, 5),  # Monday
            valid_until=datetime.date(2026, 6, 21),  # Sunday
        )
        renewal = create_renewal_draft(sub)
        # new_valid_from = 2026-06-22 (Monday, ISO 2026-W26); the anchored end is
        # the day before Monday of W26 2027 = 2027-06-27 — NOT the raw
        # +term_length, and the term after it restarts on ISO week 26 again.
        assert renewal.valid_from == datetime.date(2026, 6, 22)
        assert renewal.valid_until == datetime.date(2027, 6, 27)
        next_start = renewal.valid_until + datetime.timedelta(days=1)
        assert next_start.isocalendar()[1] == 26

    def test_preserves_term_length_when_neither_mode_configured(self, tenant):
        _make_settings(
            tenant,
            subscriptions_end_after_one_year=False,
            subscriptions_end_at_end_of_season=False,
        )
        sub = _renewable_sub()
        renewal = create_renewal_draft(sub)
        # Backward-compatible fallback: keep the predecessor's exact term length.
        assert renewal.valid_until == renewal.valid_from + (
            sub.valid_until - sub.valid_from
        )


@pytest.mark.django_db
class TestRunRenewals:
    def test_creates_draft_for_subscription_past_deadline(self, tenant):
        sub = _renewable_sub()

        result = run_renewals(_TODAY, _MIN_WEEKS)

        assert result == {"created": 1, "failed": []}
        renewal = Subscription.objects.get(previous_subscription=sub)
        # An UNCONFIRMED draft — the office confirms it downstream.
        assert renewal.admin_confirmed is False
        assert renewal.member_id == sub.member_id
        assert renewal.share_type_variation_id == sub.share_type_variation_id
        assert renewal.quantity == sub.quantity
        assert renewal.payment_cycle_id == sub.payment_cycle_id
        assert renewal.default_delivery_station_day_id == (
            sub.default_delivery_station_day_id
        )
        # Term immediately follows the predecessor, same length.
        assert renewal.valid_from == sub.valid_until + datetime.timedelta(days=1)
        assert renewal.valid_until == renewal.valid_from + (
            sub.valid_until - sub.valid_from
        )
        # Chain identifier inherited; generation bumped.
        assert renewal.subscription_number == sub.subscription_number
        assert renewal.renewal_generation == sub.renewal_generation + 1

    def test_skips_trial(self, tenant):
        _renewable_sub(is_trial=True)
        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

    def test_skips_unconfirmed(self, tenant):
        _renewable_sub(admin_confirmed=False)
        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

    def test_skips_cancelled_subscription(self, tenant):
        sub = _renewable_sub()
        Subscription.objects.filter(pk=sub.pk).update(
            cancelled_at=datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC)
        )
        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

    def test_skips_cancelled_member(self, tenant):
        member = MemberFactory()
        Member.objects.filter(pk=member.pk).update(
            cancelled_at=datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC)
        )
        _renewable_sub(member=member)
        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

    def test_skips_before_deadline(self, tenant):
        # Term ends well beyond ``today + min_weeks`` — deadline not reached.
        _renewable_sub(valid_until=datetime.date(2027, 6, 27))
        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

    def test_skips_already_renewed(self, tenant):
        sub = _renewable_sub()
        run_renewals(_TODAY, _MIN_WEEKS)  # first run creates the renewal

        result = run_renewals(_TODAY, _MIN_WEEKS)  # second run is a no-op

        assert result == {"created": 0, "failed": []}
        assert Subscription.objects.filter(previous_subscription=sub).count() == 1

    def test_uses_same_size_successor_when_variation_ended(self, tenant):
        old_variation = ShareTypeVariationFactory(
            size="M", valid_from=_VALID_FROM, valid_until=_VALID_UNTIL
        )
        successor = ShareTypeVariationFactory(
            share_type=old_variation.share_type,
            size="M",
            valid_from=_VALID_UNTIL + datetime.timedelta(days=1),
        )
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=successor,
            valid_from=successor.valid_from,
            price_per_delivery=Decimal("10.00"),
        )
        sub = _renewable_sub(share_type_variation=old_variation)

        run_renewals(_TODAY, _MIN_WEEKS)

        renewal = Subscription.objects.get(previous_subscription=sub)
        assert renewal.share_type_variation_id == successor.pk

    def test_no_successor_skips_and_counts_failure(self, tenant):
        ended_variation = ShareTypeVariationFactory(
            size="L", valid_from=_VALID_FROM, valid_until=_VALID_UNTIL
        )
        sub = _renewable_sub(share_type_variation=ended_variation)

        result = run_renewals(_TODAY, _MIN_WEEKS)

        # No draft is created; the source stays renewable for the next run.
        assert result["created"] == 0
        assert len(result["failed"]) == 1
        assert result["failed"][0]["reason"] == "no_variation"
        assert result["failed"][0]["member_id"] == str(sub.member_id)
        assert not Subscription.objects.filter(previous_subscription=sub).exists()

    def test_resolves_new_price(self, tenant):
        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=_VALID_FROM,
            price_per_delivery=Decimal("42.00"),
        )
        sub = _renewable_sub(
            share_type_variation=variation, price_per_delivery=Decimal("10.00")
        )

        run_renewals(_TODAY, _MIN_WEEKS)

        renewal = Subscription.objects.get(previous_subscription=sub)
        assert renewal.price_per_delivery == Decimal("42.00")

    def test_falls_back_to_most_recent_reference_window(self, tenant):
        # No window ACTIVE at the renewal start → the fallback is the
        # variation's most recent reference window — NOT the predecessor's
        # stored price, which can be a member-chosen solidarity figure that
        # must not silently carry into the new term.
        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=_VALID_FROM,
            valid_until=_VALID_UNTIL,  # closed — ends with the old term
            price_per_delivery=Decimal("20.00"),
        )
        sub = _renewable_sub(
            share_type_variation=variation,
            price_per_delivery=Decimal("13.00"),  # solidarity — must NOT carry
        )

        run_renewals(_TODAY, _MIN_WEEKS)

        renewal = Subscription.objects.get(previous_subscription=sub)
        assert renewal.price_per_delivery == Decimal("20.00")

    def test_predecessor_solidarity_price_never_carries_without_window(self, tenant):
        # Variation has NO price window at all: even though the predecessor
        # carries a price, the renewal refuses (no_price) instead of
        # perpetuating a per-subscription figure the office never re-approved.
        from apps.commissioning.services.renewal import FAIL_NO_PRICE

        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        sub = _renewable_sub(
            share_type_variation=variation, price_per_delivery=Decimal("13.00")
        )

        result = run_renewals(_TODAY, _MIN_WEEKS)

        assert result["created"] == 0
        assert result["failed"][0]["reason"] == FAIL_NO_PRICE
        assert not Subscription.objects.filter(previous_subscription=sub).exists()

    def test_no_price_anywhere_fails_with_no_price_reason(self, tenant):
        # BIZ-7: no gross-price window at the new start AND the predecessor
        # carried no price → creating the draft would bill a €0 term on
        # confirm. Refuse it (FAIL_NO_PRICE), leave the source renewable.
        from apps.commissioning.services.renewal import FAIL_NO_PRICE

        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        sub = _renewable_sub(share_type_variation=variation, price_per_delivery=None)

        result = run_renewals(_TODAY, _MIN_WEEKS)

        assert result["created"] == 0
        assert len(result["failed"]) == 1
        assert result["failed"][0]["id"] == str(sub.pk)
        assert result["failed"][0]["reason"] == FAIL_NO_PRICE
        assert not Subscription.objects.filter(previous_subscription=sub).exists()

    def test_one_failure_does_not_abort_others(self, tenant):
        # Share one delivery station-day so the two subs don't each spin up a
        # day_number=2 SharesDeliveryDay (global one-open-per-day_number scope).
        dsd = DeliveryStationDayFactory()
        good = _renewable_sub(default_delivery_station_day=dsd)
        # Isolate this variation on its OWN share type: ``good``'s auto-created
        # variation uses the factory's global size Iterator, which can land on
        # "L" and collide with an explicit ``size="L"`` here on the shared
        # (get_or_create) HARVEST_SHARE type — an order-dependent one-open-per-
        # type-size flake surfaced by other tests' factory calls.
        ended_variation = ShareTypeVariationFactory(
            share_type=ShareTypeFactory(share_option="HARVEST_SHARE_FRUIT"),
            size="L",
            valid_from=_VALID_FROM,
            valid_until=_VALID_UNTIL,
        )
        bad = _renewable_sub(
            share_type_variation=ended_variation, default_delivery_station_day=dsd
        )

        result = run_renewals(_TODAY, _MIN_WEEKS)

        assert result["created"] == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["id"] == str(bad.pk)
        assert Subscription.objects.filter(previous_subscription=good).exists()
        assert not Subscription.objects.filter(previous_subscription=bad).exists()

    def test_chain_display_id(self, tenant):
        sub = _renewable_sub()
        run_renewals(_TODAY, _MIN_WEEKS)
        renewal = Subscription.objects.get(previous_subscription=sub)

        assert sub.renewal_display_id == str(sub.subscription_number)
        assert renewal.renewal_display_id == f"{sub.subscription_number}a"


@pytest.mark.django_db
class TestResolveVariationForTerm:
    def test_returns_open_variation_covering_term(self, tenant):
        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        resolved = resolve_variation_for_term(
            variation, datetime.date(2027, 1, 4), datetime.date(2027, 12, 26)
        )
        assert resolved is not None
        assert resolved.pk == variation.pk

    def test_returns_none_on_gap(self, tenant):
        ended = ShareTypeVariationFactory(
            size="S", valid_from=_VALID_FROM, valid_until=_VALID_UNTIL
        )
        resolved = resolve_variation_for_term(
            ended,
            _VALID_UNTIL + datetime.timedelta(days=1),
            datetime.date(2027, 12, 26),
        )
        assert resolved is None


@pytest.mark.django_db
class TestCreateRenewalDraft:
    def test_links_predecessor_and_inherits_chain_number(self, tenant):
        sub = _renewable_sub()
        renewal = create_renewal_draft(sub)
        assert renewal.previous_subscription_id == sub.pk
        assert renewal.subscription_number == sub.subscription_number
        assert renewal.renewal_generation == 1
        assert renewal.admin_confirmed is False

    def test_only_one_renewal_per_predecessor(self, tenant):
        # REN-1: a duplicate/forked renewal is rejected. The normal path catches
        # it early via full_clean() (ValidationError); the DB partial-unique
        # index is the race backstop (a concurrent insert slipping past
        # full_clean → IntegrityError), proven here by bypassing full_clean with
        # bulk_create. Both are caught by ``_renewal_business_errors``.
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import IntegrityError, transaction

        sub = _renewable_sub()
        first = create_renewal_draft(sub)

        with pytest.raises(DjangoValidationError):
            create_renewal_draft(sub)

        dup = Subscription(
            member=sub.member,
            share_type_variation=sub.share_type_variation,
            previous_subscription=sub,
            valid_from=first.valid_from,
            valid_until=first.valid_until,
            quantity=1,
            payment_cycle=sub.payment_cycle,
            subscription_number=sub.subscription_number,
            renewal_generation=2,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Subscription.objects.bulk_create([dup])


@pytest.mark.django_db
class TestBulkRenew:
    def test_renews_eligible_skips_ineligible_with_reason(self, tenant):
        from apps.commissioning.services.renewal import bulk_renew

        dsd = DeliveryStationDayFactory()
        eligible = _renewable_sub(default_delivery_station_day=dsd)
        trial = _renewable_sub(is_trial=True, default_delivery_station_day=dsd)

        result = bulk_renew([eligible.pk, trial.pk])

        assert result["created"] == 1
        assert result["failed"] == []
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["id"] == trial.pk
        assert result["skipped"][0]["reason"] == "trial"
        assert Subscription.objects.filter(previous_subscription=eligible).exists()
        assert not Subscription.objects.filter(previous_subscription=trial).exists()

    def test_skips_already_renewed_with_reason(self, tenant):
        from apps.commissioning.services.renewal import bulk_renew

        sub = _renewable_sub()
        bulk_renew([sub.pk])  # first renewal
        result = bulk_renew([sub.pk])  # already renewed → skipped
        assert result["created"] == 0
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "already_renewed"
        assert Subscription.objects.filter(previous_subscription=sub).count() == 1

    def test_failed_carries_no_variation_reason(self, tenant):
        from apps.commissioning.services.renewal import bulk_renew

        ended = ShareTypeVariationFactory(
            size="L", valid_from=_VALID_FROM, valid_until=_VALID_UNTIL
        )
        sub = _renewable_sub(share_type_variation=ended)

        result = bulk_renew([sub.pk])

        assert result["created"] == 0
        assert result["skipped"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["reason"] == "no_variation"
        assert not Subscription.objects.filter(previous_subscription=sub).exists()

    def test_endpoint_renews_selected(self, api_client, tenant):
        from django.urls import reverse

        sub = _renewable_sub()
        resp = api_client.post(
            reverse("abos-bulk-renew"),
            {"subscription_ids": [sub.pk]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["created"] == 1
        assert Subscription.objects.filter(previous_subscription=sub).exists()

    def test_endpoint_rejects_empty_list(self, api_client, tenant):
        from django.urls import reverse

        resp = api_client.post(
            reverse("abos-bulk-renew"), {"subscription_ids": []}, format="json"
        )
        assert resp.status_code == 400


class TestRenewalFailureDigest:
    """REN-2: the daily sweep emails the office a digest of who could NOT be
    renewed and why — so failures aren't invisible in a log counter."""

    def _tenant_stub(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        tenant = MagicMock()
        tenant.email = "office@example.com"
        tenant.name = "Demo-Solawi"
        tenant.tenant_language = "de"
        tenant.schema_name = "test_pytest"
        tenant.domains.filter.return_value.first.return_value = SimpleNamespace(
            domain="demo.example"
        )
        return tenant

    def test_digest_sent_with_member_and_reason(self, monkeypatch):
        import apps.commissioning.tasks as tasks

        sent: dict = {}

        class FakeEmailService:
            def __init__(self, schema_name=None):
                sent["schema"] = schema_name

            def send_email(self, **kwargs):
                sent["kwargs"] = kwargs
                return True

        monkeypatch.setattr(
            "apps.shared.tenants.email_service.EmailService", FakeEmailService
        )
        failed = [
            {
                "id": "abc",
                "label": "17",
                "reason": "no_variation",
                "member_id": "m1",
                "member_name": "Lukas Meyer",
                "member_number": "204",
            }
        ]

        tasks._notify_office_of_renewal_failures(
            self._tenant_stub(), failed, _VALID_UNTIL
        )

        kwargs = sent["kwargs"]
        assert kwargs["slug"] == "commissioning.subscription_renewal_failures_office"
        assert kwargs["to_emails"] == ["office@example.com"]
        ctx = kwargs["context"]
        assert ctx["failure_count"] == "1"
        assert "Lukas Meyer" in ctx["renewal_failures_html"]
        assert "Lukas Meyer" in ctx["renewal_failures_text"]
        # the reason renders as human text, not the bare code
        assert "no_variation" not in ctx["renewal_failures_text"]

    def test_digest_skipped_without_office_email(self, monkeypatch):
        import apps.commissioning.tasks as tasks

        called = {"sent": False}

        class FakeEmailService:
            def __init__(self, schema_name=None):
                pass

            def send_email(self, **kwargs):
                called["sent"] = True
                return True

        monkeypatch.setattr(
            "apps.shared.tenants.email_service.EmailService", FakeEmailService
        )
        tenant = self._tenant_stub()
        tenant.email = None

        tasks._notify_office_of_renewal_failures(
            tenant, [{"reason": "invalid"}], _TODAY
        )

        assert called["sent"] is False


@pytest.mark.django_db
class TestRenewalEligibilityGuards:
    def test_inactive_member_not_swept_and_skipped_manually(self, tenant):
        # is_active=False is currently only set by GDPR anonymisation — such a
        # member must never be renewed, by the sweep OR the office button.
        from apps.commissioning.services.renewal import (
            SKIP_MEMBER_INACTIVE,
            bulk_renew,
        )

        member = MemberFactory(is_active=False)
        sub = _renewable_sub(member=member)

        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

        result = bulk_renew([sub.pk])
        assert result["created"] == 0
        assert result["skipped"][0]["reason"] == SKIP_MEMBER_INACTIVE
        assert not Subscription.objects.filter(previous_subscription=sub).exists()

    def test_short_term_not_renewed_before_it_starts(self, tenant):
        # A term SHORTER than the notice period has its cancellation deadline
        # before its own start — without the valid_from guard it would
        # auto-renew on day one, before the member ever received a delivery.
        sub = _renewable_sub(
            valid_from=datetime.date(2026, 12, 7),  # Monday, AFTER _TODAY
            valid_until=datetime.date(2026, 12, 27),  # Sunday — inside window
        )

        assert run_renewals(_TODAY, _MIN_WEEKS) == {"created": 0, "failed": []}

        # Once the term has started, the sweep picks it up.
        result = run_renewals(datetime.date(2026, 12, 7), _MIN_WEEKS)
        assert result["created"] == 1
        assert Subscription.objects.filter(previous_subscription=sub).exists()


@pytest.mark.django_db
class TestRenewalChainNumberGuard:
    def test_null_predecessor_number_refuses_instead_of_forking(self, tenant):
        # A renewal must never become a chain root: if the predecessor has no
        # subscription_number (created bypassing save() — bulk_create/import),
        # renewal refuses loudly instead of assigning a fresh number at
        # generation=0 and silently splitting the chain.
        from apps.commissioning.errors import RenewalChainNumberMissing

        sub = _renewable_sub()
        Subscription.objects.filter(pk=sub.pk).update(subscription_number=None)
        sub.refresh_from_db()

        with pytest.raises(RenewalChainNumberMissing):
            create_renewal_draft(sub)

        assert not Subscription.objects.filter(previous_subscription=sub).exists()

    def test_bulk_renew_counts_missing_chain_number_as_failed_row(self, tenant):
        from apps.commissioning.services.renewal import FAIL_INVALID, bulk_renew

        sub = _renewable_sub()
        Subscription.objects.filter(pk=sub.pk).update(subscription_number=None)

        result = bulk_renew([sub.pk])

        assert result["created"] == 0
        assert result["failed"][0]["reason"] == FAIL_INVALID


@pytest.mark.django_db
class TestBulkRenewCap:
    def test_endpoint_rejects_more_than_500_ids(self, api_client, tenant):
        from django.urls import reverse

        resp = api_client.post(
            reverse("abos-bulk-renew"),
            {"subscription_ids": [str(i) for i in range(501)]},
            format="json",
        )

        assert resp.status_code == 400
        assert resp.data["code"] == "subscription.bulk_renew.too_many_ids"


@pytest.mark.django_db
class TestGrossPriceOverlapExclusion:
    def test_overlapping_windows_rejected_by_db(self, tenant):
        # The Python overlap check in TimeBoundMixin is TOCTOU-racy; the GiST
        # exclusion constraint is the DB backstop. bulk_create bypasses
        # full_clean, so the IntegrityError here proves the DB layer holds.
        from django.db import IntegrityError, transaction

        from apps.commissioning.models import ShareTypeVariationGrossPrice

        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=_VALID_FROM,
            valid_until=_VALID_UNTIL,
            price_per_delivery=Decimal("20.00"),
        )

        overlapping = ShareTypeVariationGrossPrice(
            share_type_variation=variation,
            # starts inside the existing window
            valid_from=datetime.date(2026, 6, 1),
            valid_until=None,
            price_per_delivery=Decimal("21.00"),
            tax_rate=Decimal("10.00"),
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ShareTypeVariationGrossPrice.objects.bulk_create([overlapping])

    def test_adjacent_windows_allowed(self, tenant):
        # Inclusive [valid_from, valid_until] semantics: a window starting the
        # day after another ends must NOT conflict.
        from apps.commissioning.models import ShareTypeVariationGrossPrice

        variation = ShareTypeVariationFactory(valid_from=_VALID_FROM)
        ShareTypeVariationGrossPriceFactory(
            share_type_variation=variation,
            valid_from=_VALID_FROM,
            valid_until=_VALID_UNTIL,
            price_per_delivery=Decimal("20.00"),
        )

        adjacent = ShareTypeVariationGrossPrice(
            share_type_variation=variation,
            valid_from=_VALID_UNTIL + datetime.timedelta(days=1),
            valid_until=None,
            price_per_delivery=Decimal("21.00"),
            tax_rate=Decimal("10.00"),
        )
        ShareTypeVariationGrossPrice.objects.bulk_create([adjacent])
        assert (
            ShareTypeVariationGrossPrice.objects.filter(
                share_type_variation=variation
            ).count()
            == 2
        )


@pytest.mark.django_db
class TestRenewalValidUntilOverride:
    """The office bulk-renew modal can set ONE common end date for the batch;
    omitting it keeps each predecessor's term length."""

    def test_create_renewal_draft_honours_override(self, tenant):
        from isoweek import Week

        sub = _renewable_sub()
        override = Week(2028, 26).sunday()  # a Sunday past the default term end
        renewal = create_renewal_draft(sub, new_valid_until=override)
        assert renewal.valid_from == sub.valid_until + datetime.timedelta(days=1)
        assert renewal.valid_until == override

    def test_create_renewal_draft_default_keeps_term_length(self, tenant):
        sub = _renewable_sub()
        renewal = create_renewal_draft(sub)
        assert renewal.valid_until == renewal.valid_from + (
            sub.valid_until - sub.valid_from
        )

    def test_bulk_renew_applies_override_to_all(self, tenant):
        from isoweek import Week

        from apps.commissioning.services.renewal import bulk_renew

        sub = _renewable_sub()
        override = Week(2028, 26).sunday()
        result = bulk_renew([str(sub.pk)], new_valid_until=override)
        assert result["created"] == 1
        renewal = Subscription.objects.get(previous_subscription=sub)
        assert renewal.valid_until == override
