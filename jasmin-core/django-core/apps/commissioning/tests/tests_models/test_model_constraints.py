"""Tests for recent model-level invariants (batches BB, L, Z).

- BB: ``OrderContent.delete()`` cascades to the ``Order`` when the last
  content row is removed.
- L : ``MovementShareArticle`` DB-level XOR CheckConstraint
  ``movementsharearticle_exactly_one_source``.
- Z : ``ShareDelivery.clean()`` enforces that the subscription's
  ``share_type_variation`` matches the share's.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.commissioning.models import Order, OrderContent
from apps.commissioning.tests.factories import (
    HarvestFactory,
    MovementShareArticleFactory,
    OrderContentFactory,
    OrderFactory,
    ShareArticleFactory,
    ShareDeliveryFactory,
    ShareFactory,
    ShareTypeVariationFactory,
    SubscriptionFactory,
)
from apps.commissioning.tests.factories.days import DeliveryStationDayFactory


# ───────────────────────────── BB ─────────────────────────────
@pytest.mark.django_db
class TestOrderContentDeleteCascadesToOrder:
    def test_deleting_last_content_deletes_order(self, tenant):
        order = OrderFactory()
        content = OrderContentFactory(order=order)

        content.delete()

        assert not Order.objects.filter(pk=order.pk).exists()

    def test_deleting_one_of_many_keeps_order(self, tenant):
        order = OrderFactory()
        content_a = OrderContentFactory(order=order)
        OrderContentFactory(order=order)

        content_a.delete()

        assert Order.objects.filter(pk=order.pk).exists()
        assert OrderContent.objects.filter(order=order).count() == 1


# ───────────────────────────── L ──────────────────────────────
@pytest.mark.django_db
class TestMovementShareArticleSourceXor:
    """DB-level CheckConstraint: exactly one source FK on non-INVENTORY rows."""

    def test_two_source_fks_raises_integrity_error(self, tenant):
        article = ShareArticleFactory()
        harvest_a = HarvestFactory(share_article=article, day_number=1)
        _harvest_b = HarvestFactory(share_article=article, day_number=2)

        # Bypass save()/clean() by using QuerySet.update() on a freshly
        # inserted row — the DB constraint must still fire.
        movement = MovementShareArticleFactory(
            share_article=article,
            harvest=harvest_a,
            movement_type="HARVEST",
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                type(movement).objects.filter(pk=movement.pk).update(
                    purchase=None,
                    harvest=harvest_a,
                    # Force a second source FK on the same row via raw update
                    order_content=OrderContentFactory(),
                )

    def test_inventory_with_source_fk_raises_integrity_error(self, tenant):
        article = ShareArticleFactory()
        harvest = HarvestFactory(share_article=article)

        movement = MovementShareArticleFactory(
            share_article=article,
            harvest=harvest,
            movement_type="HARVEST",
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                type(movement).objects.filter(pk=movement.pk).update(
                    movement_type="INVENTORY"
                )


# ───────────────────────────── Z ──────────────────────────────
@pytest.mark.django_db
class TestShareDeliveryVariationConsistency:
    def test_matching_variation_is_valid(self, tenant):
        variation = ShareTypeVariationFactory()
        share = ShareFactory(share_type_variation=variation)
        # Reuse the share's delivery_day everywhere so neither
        # SharesDeliveryDay (day_number) nor DeliveryStationDay
        # (delivery_station, delivery_day) overlap rules fire.
        dsd = DeliveryStationDayFactory(delivery_day=share.delivery_day)
        subscription = SubscriptionFactory(
            share_type_variation=variation, default_delivery_station_day=dsd
        )

        delivery = ShareDeliveryFactory(
            share=share, subscription=subscription, delivery_station_day=dsd
        )

        assert delivery.pk is not None

    def test_mismatched_variation_raises(self, tenant):
        # Explicit, distinct sizes: both variations share the one HARVEST_SHARE
        # ShareType (factory get_or_create), so they must differ on ``size`` or
        # they'd collide on the (share_type, size) overlap rule during setup.
        variation_a = ShareTypeVariationFactory(size="M")
        variation_b = ShareTypeVariationFactory(size="L")
        share = ShareFactory(share_type_variation=variation_a)
        dsd = DeliveryStationDayFactory(delivery_day=share.delivery_day)
        subscription = SubscriptionFactory(
            share_type_variation=variation_b, default_delivery_station_day=dsd
        )

        with pytest.raises(ValidationError):
            ShareDeliveryFactory(
                share=share, subscription=subscription, delivery_station_day=dsd
            )


# ───────────── On-off opt-in × jokers mutual exclusion ─────────────
@pytest.mark.django_db
class TestOnOffJokerMutualExclusion:
    """Jokers (per-period opt-OUT) and on-off opt-in (per-period opt-IN) can't
    coexist on the same share type — both ``ShareTypeVariation.clean`` and
    ``ShareType.clean`` forbid the combination, in either save order."""

    @staticmethod
    def _enable_optin() -> None:
        # The variation-side guard sits behind the tenant on-off gate, so the
        # tenant must have the feature enabled to reach the joker check.
        import datetime

        from django.db import connection
        from django.utils import timezone

        from apps.shared.tenants.models import TenantSettings

        settings = TenantSettings.get_current_settings(connection.tenant)
        if settings is None:
            settings = TenantSettings.objects.create(
                tenant=connection.tenant,
                valid_from=timezone.now() - datetime.timedelta(seconds=1),
            )
        settings.allows_share_type_variation_optin = True
        settings.save()

    def test_optin_variation_on_jokered_share_type_rejected(self, tenant):
        from apps.commissioning.models import ShareType

        self._enable_optin()
        variation = ShareTypeVariationFactory(requires_optin=True)
        # Stamp jokers via .update() — saving the share type would itself trip
        # the reverse guard (proving it fires on save); here we isolate the
        # variation-side guard.
        ShareType.objects.filter(pk=variation.share_type_id).update(amount_of_jokers=2)
        variation.share_type.refresh_from_db()

        with pytest.raises(ValidationError) as exc:
            variation.clean()
        assert "requires_optin" in exc.value.message_dict

    def test_jokers_on_share_type_with_optin_variation_rejected(self, tenant):
        # Reverse direction — no tenant gate involved on ShareType.clean.
        variation = ShareTypeVariationFactory(requires_optin=True)
        share_type = variation.share_type
        share_type.amount_of_donation_jokers = 1

        with pytest.raises(ValidationError) as exc:
            share_type.clean()
        assert "amount_of_jokers" in exc.value.message_dict

    def test_optin_variation_without_jokers_passes(self, tenant):
        self._enable_optin()
        variation = ShareTypeVariationFactory(requires_optin=True)
        # 0 jokers (factory default) → joker guard not triggered.
        variation.clean()
