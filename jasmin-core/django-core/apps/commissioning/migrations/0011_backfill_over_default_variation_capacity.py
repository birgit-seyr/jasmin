"""Backfill any ShareTypeVariation left over-capacity by 0008.

Migration 0008 made ``ShareTypeVariation.capacity`` NOT NULL with a default of
100, silently capping any previously-"unlimited" (NULL) variation. A variation
whose live occupancy already exceeded 100 would otherwise be instantly "full"
and mass-waitlist every new subscribe on deploy.

Which rows were previously NULL is no longer knowable, so we key off the current
state instead: raise ``capacity`` to at least the total quantity of its
current-or-future active confirmed subscriptions (a safe UPPER bound on the
per-week concurrent peak — never leaves a row over its cap). Raise-only, so a
legitimately-capped row that happens to sit right at its cap is untouched.

Forward-only (CLAUDE.md): reverse is a noop — we can't know the pre-backfill
values, and past weeks are immutable. Uses the historical models (not the
service) so a fresh-DB replay stays schema-safe.
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import Q, Sum
from django.utils import timezone


def backfill_variation_capacity(apps, schema_editor):
    ShareTypeVariation = apps.get_model("commissioning", "ShareTypeVariation")
    Subscription = apps.get_model("commissioning", "Subscription")

    today = timezone.now().date()
    for variation in ShareTypeVariation.objects.all():
        total = (
            Subscription.objects.filter(
                share_type_variation_id=variation.pk,
                admin_confirmed=True,
                cancelled_at__isnull=True,
                on_waiting_list=False,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .aggregate(q=Sum("quantity"))["q"]
            or 0
        )
        if variation.capacity < total:
            ShareTypeVariation.objects.filter(pk=variation.pk).update(capacity=total)


class Migration(migrations.Migration):
    dependencies = [
        ("commissioning", "0010_member_notification_token_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_variation_capacity, migrations.RunPython.noop),
    ]
