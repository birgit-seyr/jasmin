"""Seed N realistic demo Members so the office UI has data to browse.

Usage:
    python manage.py seed_demo_members --schema=<tenant_schema>
    python manage.py seed_demo_members --schema=<tenant_schema> --count=50
    python manage.py seed_demo_members --schema=<tenant_schema> --clean

Generates a varied member roster with deterministic distributions
(seedable via ``--seed``). Re-running is idempotent: emails are tagged
with ``demo_seed_member_NN@example.com`` and look-ups use that as the
unique key. ``--clean`` deletes only rows this command created.

Variation across the roster:

  * ~70% admin-confirmed (member_number assigned), ~30% pending.
  * ~60% have a linked ``JasminUser`` (password ``Test-Test-2026`` — any of
    these can log in to exercise member flows), ~40% don't.
  * ~10% trial members, ~5% inactive, the rest active.
  * 0-10 ``CoopShare`` rows per member with a believable distribution
    (1 share most common). ~70% paid (paid_at set), ~30% pending.
  * 0-3 ``Subscription`` rows per member, spread across share-type
    variations the catalogue exposes. Mix of past/active/future, mix
    of admin-confirmed and pending, occasional trial sub.

Catalogue prerequisites: the tenant must already have at least one
``ShareTypeVariation``, ``PaymentCycle`` and ``DeliveryStationDay``
(configure via the office UI). The command exits with a friendly
message if any is missing.

Side effects: subscriptions are persisted with ``admin_confirmed``
set directly — the ``_post_confirm`` materialise step (Shares /
ShareDeliveries / ChargeSchedule) is NOT run. If you need the
downstream rows too, re-confirm a subscription through the office UI
or extend the command to call ``Subscription.confirm()`` explicitly.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.accounts.models import JasminUser
from apps.authz.roles import Role
from apps.commissioning.models import (
    CoopShare,
    DeliveryStationDay,
    Member,
    PaymentCycle,
    ShareTypeVariation,
    Subscription,
)
from apps.shared.tenants.models import Tenant

EMAIL_PREFIX = "demo_seed_member_"
PASSWORD = "Test-Test-2026"


class Command(BaseCommand):
    help = (
        "Seed N varied demo Members (with optional users, coop shares and "
        "subscriptions) for office-UI dev. Idempotent + cleanable."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--schema", required=True, help="Tenant schema name")
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="How many demo members to seed (default 50).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for reproducible distributions (default 42).",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Remove only the rows this command created (matched by email prefix).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        schema = options["schema"]
        try:
            Tenant.objects.get(schema_name=schema)
        except Tenant.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Tenant '{schema}' not found."))
            return

        with schema_context(schema):
            if options["clean"]:
                self._clean()
                return
            self._check_catalogue()
            self._seed(count=options["count"], seed=options["seed"])

    # ------------------------------------------------------------------
    # Clean
    # ------------------------------------------------------------------
    def _clean(self) -> None:
        # CoopShares and Subscriptions cascade off Member; users we
        # delete explicitly because the OneToOne ``user`` link uses
        # SET_NULL on Member but we want the user gone too.
        members = Member.objects.filter(email__startswith=EMAIL_PREFIX)
        user_ids = list(
            members.exclude(user__isnull=True).values_list("user_id", flat=True)
        )
        n_members = members.count()
        members.delete()
        n_users = JasminUser.objects.filter(id__in=user_ids).delete()[0]
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {n_members} demo member(s) and {n_users} linked user(s)."
            )
        )

    # ------------------------------------------------------------------
    # Catalogue prerequisites
    # ------------------------------------------------------------------
    def _check_catalogue(self) -> None:
        missing: list[str] = []
        variations = list(ShareTypeVariation.objects.all())
        cycles = list(PaymentCycle.objects.filter(is_active=True))
        # ``DeliveryStationDay`` is time-bound (TimeBoundMixin): "currently
        # open" rows are the ones whose ``valid_until`` is NULL. We don't
        # filter on ``valid_from`` because back-dated subs need DSDs that
        # were valid in the past too; subscription creation later picks a
        # row whose window covers the candidate ``valid_from``.
        delivery_station_days = list(
            DeliveryStationDay.objects.filter(valid_until__isnull=True)
        )
        if not variations:
            missing.append("ShareTypeVariation")
        if not cycles:
            missing.append("PaymentCycle (active)")
        if not delivery_station_days:
            missing.append("DeliveryStationDay (open / valid_until IS NULL)")
        if missing:
            raise SystemExit(
                "Cannot seed demo members — the tenant catalogue is missing: "
                + ", ".join(missing)
                + ".\nConfigure these via the office UI first."
            )

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------
    def _seed(self, *, count: int, seed: int) -> None:
        rng = random.Random(seed)
        variations = list(ShareTypeVariation.objects.all())
        cycles = list(PaymentCycle.objects.filter(is_active=True))
        delivery_station_days = list(
            DeliveryStationDay.objects.filter(valid_until__isnull=True)
        )

        first_names = _NAMES_FIRST
        last_names = _NAMES_LAST
        today = timezone.now().date()

        confirmed_count = paid_share_count = subs_count = users_count = 0

        for idx in range(count):
            email = f"{EMAIL_PREFIX}{idx:02d}@example.com"
            first = rng.choice(first_names)
            last = rng.choice(last_names)

            # 60% of demo members get a login. ``test`` password is the
            # same as ``seed_test_users`` so the muscle memory carries
            # over for office staff.
            has_user = rng.random() < 0.60
            user = None
            if has_user:
                user, _ = JasminUser.objects.get_or_create(
                    email=email,
                    defaults={
                        "first_name": first,
                        "last_name": last,
                        "username": email,
                        "roles": [Role.MEMBER],
                        "account_status": "active",
                    },
                )
                user.set_password(PASSWORD)
                user.save()
                users_count += 1

            with transaction.atomic():
                member, created = Member.objects.get_or_create(
                    email=email,
                    defaults={
                        "first_name": first,
                        "last_name": last,
                        "is_active": rng.random() > 0.05,  # 5% inactive
                        "is_trial": rng.random() < 0.10,  # 10% trial
                        "user": user,
                    },
                )
                if not created:
                    # Idempotent: skip the variation graph if the member
                    # already has any. Re-runs after a partial seed will
                    # still fill in users + reset passwords above.
                    if member.user_id != getattr(user, "id", None):
                        member.user = user
                        member.save(update_fields=["user"])
                    if CoopShare.objects.filter(member=member).exists() or (
                        Subscription.objects.filter(member=member).exists()
                    ):
                        continue

                # 70% confirmed. confirm() runs the post-confirm hook
                # (member_number assignment); the rest stay pending.
                is_confirmed = rng.random() < 0.70
                if is_confirmed:
                    # Confirm without an admin actor — the model doesn't
                    # require one for dev seeding.
                    member.admin_confirmed = True
                    member.admin_confirmed_at = timezone.now()
                    member._generate_member_number()
                    member.entry_date = today - timedelta(days=rng.randint(30, 365 * 2))
                    member.save(
                        update_fields=[
                            "admin_confirmed",
                            "admin_confirmed_at",
                            "entry_date",
                        ]
                    )
                    confirmed_count += 1

                # CoopShares — weighted distribution, then 70%/30% paid/pending.
                share_count = _weighted_choice(
                    rng,
                    [(0, 10), (1, 50), (2, 20), (3, 10), (5, 7), (10, 3)],
                )
                for _ in range(share_count):
                    due = today - timedelta(days=rng.randint(0, 365))
                    paid_at = (
                        timezone.now() - timedelta(days=rng.randint(0, 300))
                        if rng.random() < 0.70
                        else None
                    )
                    CoopShare.objects.create(
                        member=member,
                        amount_of_coop_shares=Decimal(rng.choice([1, 1, 1, 2, 5])),
                        due_date=due,
                        paid_at=paid_at,
                        admin_confirmed=is_confirmed,
                        admin_confirmed_at=(timezone.now() if is_confirmed else None),
                    )
                    if paid_at is not None:
                        paid_share_count += 1

                # Subscriptions — 0..3, each on a distinct variation; a
                # member can hold multiple subscriptions.
                if is_confirmed:
                    sub_count = _weighted_choice(
                        rng, [(0, 30), (1, 50), (2, 15), (3, 5)]
                    )
                else:
                    # Unconfirmed members usually still have a pending sub.
                    sub_count = _weighted_choice(rng, [(0, 70), (1, 30)])
                chosen_variations = rng.sample(
                    variations, k=min(sub_count, len(variations))
                )
                for variation in chosen_variations:
                    if self._create_subscription(
                        rng=rng,
                        member=member,
                        variation=variation,
                        cycles=cycles,
                        delivery_station_days=delivery_station_days,
                        is_member_confirmed=is_confirmed,
                        today=today,
                    ):
                        subs_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {count} demo member(s): "
                f"{confirmed_count} confirmed, "
                f"{users_count} with login (password={PASSWORD!r}), "
                f"{paid_share_count} paid coop shares, "
                f"{subs_count} subscriptions."
            )
        )

    def _create_subscription(
        self,
        *,
        rng: random.Random,
        member: Member,
        variation: ShareTypeVariation,
        cycles: list[PaymentCycle],
        delivery_station_days: list[DeliveryStationDay],
        is_member_confirmed: bool,
        today: date,
    ) -> bool:
        """Create one subscription. Returns ``True`` if persisted,
        ``False`` if skipped because no DSD covers the chosen window."""
        # Place each sub in one of: past-active (60%), future (20%),
        # expired (20%). ``valid_from`` lands on a Monday per
        # CLAUDE.md ("valid_from dates are always mondays").
        bucket = _weighted_choice(
            rng, [("active", 60), ("future", 20), ("expired", 20)]
        )
        if bucket == "active":
            offset = rng.randint(7, 365)
            valid_from = _previous_monday(today - timedelta(days=offset))
            valid_until = None
        elif bucket == "future":
            offset = rng.randint(7, 90)
            valid_from = _previous_monday(today + timedelta(days=offset))
            valid_until = None
        else:  # expired
            offset = rng.randint(180, 730)
            valid_from = _previous_monday(today - timedelta(days=offset))
            valid_until = _previous_monday(today - timedelta(days=rng.randint(7, 90)))

        is_trial = rng.random() < 0.15
        is_confirmed = is_member_confirmed and rng.random() < 0.80
        cycle = rng.choice(cycles)

        # ``Subscription.save()`` runs ``full_clean()`` which enforces
        # the DSD coverage rule: the picked DSD's ``valid_from`` must
        # be <= sub.valid_from, and its ``valid_until`` (if any) must
        # be >= sub.valid_until. Filter the candidate pool first; if
        # nothing fits the chosen window, skip this sub rather than
        # crashing the whole seed.
        compatible_delivery_station_days = [
            delivery_station_day
            for delivery_station_day in delivery_station_days
            if delivery_station_day.valid_from <= valid_from
            and (
                delivery_station_day.valid_until is None
                or valid_until is None
                or delivery_station_day.valid_until >= valid_until
            )
        ]
        if not compatible_delivery_station_days:
            return False
        delivery_station_day = rng.choice(compatible_delivery_station_days)

        Subscription.objects.create(
            member=member,
            share_type_variation=variation,
            valid_from=valid_from,
            valid_until=valid_until,
            quantity=rng.choice([1, 1, 1, 2]),
            payment_cycle=cycle,
            default_delivery_station_day=delivery_station_day,
            is_trial=is_trial,
            admin_confirmed=is_confirmed,
            admin_confirmed_at=timezone.now() if is_confirmed else None,
        )
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weighted_choice(rng: random.Random, choices: list[tuple[Any, int]]) -> Any:
    total = sum(weight for _, weight in choices)
    pick = rng.randint(1, total)
    cum = 0
    for value, weight in choices:
        cum += weight
        if pick <= cum:
            return value
    return choices[-1][0]


def _previous_monday(d: date) -> date:
    from apps.commissioning.utils.iso_week_utils import previous_monday

    return previous_monday(d)


# A small canned pool — we don't need Faker for a 50-row dev seed and
# keeping the names hard-coded keeps re-runs identical across machines.
_NAMES_FIRST: list[str] = [
    "Anja",
    "Ben",
    "Clara",
    "David",
    "Elena",
    "Felix",
    "Greta",
    "Hans",
    "Ines",
    "Jonas",
    "Katja",
    "Lukas",
    "Maria",
    "Niklas",
    "Olga",
    "Pia",
    "Quentin",
    "Rosa",
    "Stefan",
    "Tanja",
    "Ulrich",
    "Vera",
    "Wolf",
    "Xenia",
    "Yannick",
    "Zoe",
]

_NAMES_LAST: list[str] = [
    "Bauer",
    "Becker",
    "Braun",
    "Fischer",
    "Hartmann",
    "Hoffmann",
    "Huber",
    "Klein",
    "Koch",
    "Krause",
    "Lange",
    "Lehmann",
    "Maier",
    "Mayer",
    "Meier",
    "Müller",
    "Neumann",
    "Richter",
    "Schmidt",
    "Schneider",
    "Schwarz",
    "Vogel",
    "Wagner",
    "Weber",
    "Wolf",
    "Zimmermann",
]
