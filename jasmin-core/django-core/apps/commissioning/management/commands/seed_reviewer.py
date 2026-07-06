"""Seed a tenant with realistic, time-spread, internally-consistent review data.

The goal is a tenant a reviewer can click through end-to-end: every list, chart
and detail page has believable rows. On top of ``seed_demo_members`` (which
creates the member roster + raw subscriptions) this command:

  1. Builds the reference catalogue subscriptions need (Season, ShareTypes +
     Variations + prices, DeliveryStations + delivery days + station-days,
     ShareArticles + net prices).
  2. Runs ``seed_demo_members`` + ``seed_consent_documents``.
  3. Materialises ~65% of the confirmed subscriptions through the REAL confirm
     path (``Subscription.confirm``) so Shares / ShareDeliveries / PLANNED
     ChargeSchedules actually exist — the raw ``admin_confirmed`` flag that
     ``seed_demo_members`` writes does NOT materialise anything.
  4. Adds a small on-waiting-list cohort.
  5. Creates SEPA BillingProfiles for most confirmed members + sets the tenant's
     SEPA creditor identity.
  6. Regenerates the charge ledger and runs a billing run (export → ISSUED),
     then hand-flips a subset of charges to PAID / PARTIAL / FAILED / WAIVED so
     the per-status totals and income chart look alive.
  7. Optionally seeds a light reseller presence (Resellers only — the
     offer/order/delivery-note/invoice document pipeline is intentionally NOT
     seeded; see the printed note).

Dev only: refuses to run when ``DEBUG`` is False. Idempotent-ish: the catalogue
is reused when it already exists and re-confirming a subscription is a no-op, so
re-running does not crash or double-seed the catalogue.

    python manage.py seed_reviewer --schema test --members 40
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Max, Min, Sum
from django.utils import timezone
from django_tenants.utils import (
    get_public_schema_name,
    schema_context,
    tenant_context,
)

from apps.accounts.models import JasminUser
from apps.authz.roles import Role
from apps.commissioning.models import (
    ContactEntity,
    CoopShare,
    DeliveryStation,
    DeliveryStationDay,
    Member,
    PaymentCycle,
    Reseller,
    Season,
    Share,
    ShareArticle,
    ShareArticleNetPrice,
    ShareDelivery,
    SharesDeliveryDay,
    ShareType,
    ShareTypeVariation,
    ShareTypeVariationGrossPrice,
    Subscription,
)
from apps.commissioning.models.choices_text import (
    DayNumberOptions,
    PaymentCycleOptions,
    ShareOptions,
    UnitOptions,
)
from apps.payments.constants import ChargeStatus, PaymentMethodOptions
from apps.payments.errors import (
    NoEligibleCharges,
    NoValidSepaMandates,
    SepaExportInvalid,
)
from apps.payments.models import BillingProfile, BillingRun, ChargeSchedule
from apps.payments.services import BillingRunService, ChargeScheduleService
from apps.shared.tenants.models import Tenant, TenantSettings

# A valid test IBAN (Deutsche Bank test number) reused for every SEPA mandate —
# passes ``validate_iban`` and the sepaxml schema check.
TEST_IBAN = "DE89370400440532013000"
ADMIN_EMAIL = "reviewer-seed@example.com"


class Command(BaseCommand):
    help = (
        "Seed a tenant with realistic, time-spread review data: catalogue + "
        "members + materialised subscriptions + billing run. Dev only."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--schema", required=True, help="Tenant schema name")
        parser.add_argument(
            "--members",
            type=int,
            default=40,
            help="How many demo members to seed (default 40).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for reproducible distributions (default 42).",
        )

    # ------------------------------------------------------------------ #
    def handle(self, *args: Any, **opts: Any) -> None:
        if not settings.DEBUG:
            raise CommandError(
                "seed_reviewer is a development helper and refuses to run with "
                "DEBUG=False. It writes fixed test credentials + placeholder "
                "SEPA data that must never reach a production schema."
            )

        schema: str = opts["schema"]
        member_count: int = opts["members"]
        rng = random.Random(opts["seed"])

        # ``Tenant`` is a SHARED (public-schema) model — validate + set the SEPA
        # creditor identity there before switching into the tenant schema.
        with schema_context(get_public_schema_name()):
            tenant = Tenant.objects.filter(schema_name=schema).first()
            if tenant is None:
                raise CommandError(f"No tenant with schema_name={schema!r}.")
            self._set_tenant_sepa_creditor(tenant)

        # Use ``tenant_context`` (not ``schema_context``): it sets
        # ``connection.tenant`` to the REAL ``Tenant`` instance. The billing-run
        # export reads ``connection.tenant.sepa_creditor_name`` directly, which
        # a ``schema_context`` FakeTenant does not carry.
        with tenant_context(tenant):
            today = timezone.localdate()
            admin_user = self._get_or_create_admin_user()
            tenant_settings = TenantSettings.get_current_settings(tenant)

            self._seed_catalogue(rng, today)

            # Members + raw subscriptions. The catalogue now exists, so
            # seed_demo_members creates bounded subscriptions too.
            call_command(
                "seed_demo_members",
                schema=schema,
                count=member_count,
                seed=opts["seed"],
            )
            call_command("seed_consent_documents", schema=schema)

            # seed_demo_members leaves ``price_per_delivery`` NULL, and the
            # billing engine bills off THAT field (not the variation gross
            # price), so every charge would otherwise be 0.00 and no SEPA run
            # could be built. Backfill it from the variation's gross price.
            self._backfill_subscription_prices()

            self._materialize_subscriptions(rng, admin_user, tenant_settings, today)
            self._seed_waiting_list(rng, today)
            self._seed_billing_profiles(rng, today)

            # Backfill the ledger for every billable subscription (idempotent —
            # only touches PLANNED rows).
            ChargeScheduleService.regenerate_all()

            self._seed_billing_run(rng, admin_user, today)
            self._seed_resellers(tenant_settings)

            self._print_summary(tenant)

    # ------------------------------------------------------------------ #
    # Tenant SEPA creditor identity (public schema)
    # ------------------------------------------------------------------ #
    def _set_tenant_sepa_creditor(self, tenant: Tenant) -> None:
        """Populate the tenant's SEPA creditor fields so the billing-run export
        can build a valid pain.008 (it raises ``SepaExportInvalid`` otherwise)."""
        changed: list[str] = []
        wanted = {
            "iban": TEST_IBAN,
            "sepa_creditor_id": "DE98ZZZ09999999999",
            "sepa_creditor_name": tenant.name or "Reviewer Solawi",
            "sepa_creditor_bic": "COBADEFFXXX",
        }
        for field, value in wanted.items():
            if not getattr(tenant, field, None):
                setattr(tenant, field, value)
                changed.append(field)
        if changed:
            tenant.save(update_fields=changed)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Set tenant SEPA creditor fields: {', '.join(changed)}."
                )
            )

    def _get_or_create_admin_user(self) -> JasminUser:
        """A privileged actor to stamp as ``admin_confirmed_by`` on confirm."""
        admin_user, _ = JasminUser.objects.get_or_create(
            email=ADMIN_EMAIL,
            defaults={
                "first_name": "Reviewer",
                "last_name": "Seeder",
                "username": ADMIN_EMAIL,
                "roles": [Role.OFFICE],
                "account_status": "active",
            },
        )
        return admin_user

    # ------------------------------------------------------------------ #
    # 1. Reference catalogue
    # ------------------------------------------------------------------ #
    def _seed_catalogue(self, rng: random.Random, today: date) -> None:
        """Build (or reuse) the catalogue subscriptions + planning need.

        Every TimeBound catalogue row is created OPEN (``valid_until=None``) with
        a ``valid_from`` far enough in the past to cover the back-dated
        (expired) subscriptions ``seed_demo_members`` generates. An open window
        trivially satisfies both the "one open per group" DB constraints and
        ``assert_delivery_station_day_covers_subscription`` for every term.
        """
        # ~2 years back, snapped to a Monday: covers the expired-subscription
        # bucket (up to ~730 days back) so their delivery-station-days match.
        catalogue_from = _previous_monday(today - timedelta(days=800))

        # -- Season (finite, Mon→Sun, spanning the current year) --
        if not Season.objects.exists():
            season_from = _previous_monday(today - timedelta(days=182))
            Season.objects.create(
                valid_from=season_from,
                valid_until=season_from + timedelta(days=363),
                weeks_without_delivery=[1, 52],
            )

        # -- PaymentCycles (migration 0002 seeds all six; ensure idempotently) --
        for choice in (PaymentCycleOptions.MONTHLY, PaymentCycleOptions.QUARTERLY):
            PaymentCycle.objects.get_or_create(
                choice=choice, defaults={"is_active": True}
            )

        # -- ShareTypes with distinct share_option + their variations/prices --
        share_type_specs = [
            (ShareOptions.HARVEST_SHARE, "Harvest Share", True, ["S", "M", "L"]),
            (
                ShareOptions.HARVEST_SHARE_FRUITS_ONLY,
                "Fruit Share",
                True,
                ["S", "M"],
            ),
            (ShareOptions.CHICKEN_SHARE, "Egg Share", False, ["HALF", "FULL"]),
            (ShareOptions.HONEY_SHARE, "Honey Share", False, ["ONE_SIZE"]),
        ]
        # Base per-delivery price by size (Decimal end-to-end — money hygiene).
        size_price = {
            "S": Decimal("14.00"),
            "M": Decimal("19.00"),
            "L": Decimal("24.00"),
            "HALF": Decimal("9.00"),
            "FULL": Decimal("16.00"),
            "ONE_SIZE": Decimal("11.00"),
        }
        variations_created = types_created = 0
        for share_option, name, complex_planning, sizes in share_type_specs:
            share_type = ShareType.objects.filter(share_option=share_option).first()
            if share_type is None:
                share_type = ShareType.objects.create(
                    name=name,
                    share_option=share_option,
                    delivery_cycle="WEEKLY",
                    needs_complex_planning=complex_planning,
                    is_additional_share_type=not complex_planning,
                    valid_from=catalogue_from,
                    valid_until=None,
                )
                types_created += 1
            for size in sizes:
                variation = ShareTypeVariation.objects.filter(
                    share_type=share_type, size=size
                ).first()
                if variation is None:
                    variation = ShareTypeVariation.objects.create(
                        share_type=share_type,
                        size=size,
                        variation_type=ShareTypeVariation.VariationType.PHYSICAL,
                        # Generous farm-wide cap so materialising many
                        # subscriptions never trips the capacity gate.
                        capacity=300,
                        valid_from=catalogue_from,
                        valid_until=None,
                    )
                    variations_created += 1
                if not ShareTypeVariationGrossPrice.objects.filter(
                    share_type_variation=variation
                ).exists():
                    ShareTypeVariationGrossPrice.objects.create(
                        share_type_variation=variation,
                        price_per_delivery=size_price.get(size, Decimal("15.00")),
                        tax_rate=Decimal("7.00"),
                        valid_from=catalogue_from,
                        valid_until=None,
                    )
        self.stdout.write(
            self.style.SUCCESS(
                f"Catalogue: {types_created} share type(s), "
                f"{variations_created} variation(s) created (existing reused)."
            )
        )

        # -- Delivery stations (one with a non-zero pickup fee) --
        station_specs = [
            ("Farm Gate", Decimal("0.00")),
            ("City Center", Decimal("1.50")),
            ("North Depot", Decimal("0.00")),
            ("West Market", Decimal("0.00")),
            ("South Hub", Decimal("0.00")),
        ]
        stations: list[DeliveryStation] = []
        for idx, (short_name, fee) in enumerate(station_specs, start=1):
            station = DeliveryStation.objects.filter(number=idx).first()
            if station is None:
                station = DeliveryStation.objects.create(
                    number=idx,
                    short_name=short_name,
                    is_active=True,
                    fee_per_box_net=fee,
                    fees_billing_period=(PaymentCycleOptions.MONTHLY if fee else None),
                )
            stations.append(station)

        # -- Shares delivery days (distinct day_number) --
        day_specs = [
            (DayNumberOptions.WEDNESDAY, "Wednesday Tour"),
            (DayNumberOptions.FRIDAY, "Friday Tour"),
            (DayNumberOptions.SATURDAY, "Saturday Tour"),
        ]
        delivery_days: list[SharesDeliveryDay] = []
        for day_number, day_name in day_specs:
            day = SharesDeliveryDay.objects.filter(day_number=day_number).first()
            if day is None:
                day = SharesDeliveryDay.objects.create(
                    day_number=day_number,
                    name=day_name,
                    default_packing_day=day_number,
                    default_harvesting_day=day_number,
                    default_washing_day=day_number,
                    default_cleaning_day=day_number,
                    default_get_current_stock_day=day_number,
                    valid_from=catalogue_from,
                    valid_until=None,
                )
            delivery_days.append(day)

        # -- Station-days: one OPEN row per (station x day), covering the year --
        dsd_created = 0
        for station in stations:
            for stop, day in enumerate(delivery_days, start=1):
                exists = DeliveryStationDay.objects.filter(
                    delivery_station=station, delivery_day=day
                ).exists()
                if not exists:
                    DeliveryStationDay.objects.create(
                        delivery_station=station,
                        delivery_day=day,
                        capacity=80,
                        tour_number=1,
                        stop_order=stop,
                        valid_from=catalogue_from,
                        valid_until=None,
                    )
                    dsd_created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Catalogue: {len(stations)} station(s), {len(delivery_days)} "
                f"delivery day(s), {dsd_created} station-day(s) created."
            )
        )

        # -- Share articles (+ current net price) --
        article_specs = [
            ("Carrots", UnitOptions.KG, ShareOptions.HARVEST_SHARE, False, False),
            ("Potatoes", UnitOptions.KG, ShareOptions.HARVEST_SHARE, False, True),
            ("Tomatoes", UnitOptions.KG, ShareOptions.HARVEST_SHARE, False, True),
            ("Lettuce", UnitOptions.PCS, ShareOptions.HARVEST_SHARE, False, False),
            ("Spinach", UnitOptions.BUNCH, ShareOptions.HARVEST_SHARE, False, False),
            ("Onions", UnitOptions.KG, ShareOptions.HARVEST_SHARE, True, False),
            ("Cabbage", UnitOptions.PCS, ShareOptions.HARVEST_SHARE, False, True),
            ("Zucchini", UnitOptions.KG, ShareOptions.HARVEST_SHARE, False, False),
            (
                "Apples",
                UnitOptions.KG,
                ShareOptions.HARVEST_SHARE_FRUITS_ONLY,
                True,
                True,
            ),
            (
                "Pears",
                UnitOptions.KG,
                ShareOptions.HARVEST_SHARE_FRUITS_ONLY,
                True,
                False,
            ),
            ("Eggs", UnitOptions.PCS, ShareOptions.CHICKEN_SHARE, False, False),
            ("Honey", UnitOptions.PCS, ShareOptions.HONEY_SHARE, False, True),
            ("Garlic", UnitOptions.KG, ShareOptions.HARVEST_SHARE, True, False),
            ("Beetroot", UnitOptions.KG, ShareOptions.HARVEST_SHARE, False, False),
        ]
        articles_created = 0
        for idx, (name, unit, option, purchased, resold) in enumerate(
            article_specs, start=1
        ):
            article_number = f"ART-{idx:03d}"
            article = ShareArticle.objects.filter(article_number=article_number).first()
            if article is None:
                article = ShareArticle.objects.create(
                    article_number=article_number,
                    name=name,
                    is_active=True,
                    share_option=option,
                    is_purchased=purchased,
                    is_sold_to_resellers=resold,
                    organic_status=ShareArticle.OrganicStatus.ORGANIC,
                    default_movement_unit=unit,
                )
                articles_created += 1
            if not ShareArticleNetPrice.objects.filter(share_article=article).exists():
                base = Decimal("2.20") + Decimal(idx % 5) * Decimal("0.35")
                ShareArticleNetPrice.objects.create(
                    share_article=article,
                    tax_rate=Decimal("7.00"),
                    net_price_for_boxes_kg=base,
                    net_price_for_boxes_pieces=base,
                    net_price_for_orders_kg_1=base - Decimal("0.30"),
                    valid_from=catalogue_from,
                    valid_until=None,
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Catalogue: {articles_created} share article(s) created "
                f"({len(article_specs)} total)."
            )
        )

    def _backfill_subscription_prices(self) -> None:
        """Set ``price_per_delivery`` on every priceless subscription from its
        variation's current gross price (one query builds the price map — no
        N+1). The billing engine reads this field directly."""
        price_by_variation: dict[str, Decimal] = {}
        for gross in ShareTypeVariationGrossPrice.objects.order_by(
            "share_type_variation_id", "-valid_from"
        ):
            if gross.price_per_delivery is not None:
                price_by_variation.setdefault(
                    gross.share_type_variation_id, gross.price_per_delivery
                )
        updated = 0
        for subscription in Subscription.objects.filter(
            price_per_delivery__isnull=True
        ):
            price = price_by_variation.get(subscription.share_type_variation_id)
            if price is None:
                continue
            subscription.price_per_delivery = price
            try:
                subscription.save(update_fields=["price_per_delivery"])
                updated += 1
            except Exception:  # noqa: BLE001 — skip legacy open-ended rows etc.
                continue
        self.stdout.write(
            self.style.SUCCESS(f"Priced {updated} subscription(s) from gross prices.")
        )

    # ------------------------------------------------------------------ #
    # 3. Materialise a subset of subscriptions through the REAL confirm path
    # ------------------------------------------------------------------ #
    def _materialize_subscriptions(
        self,
        rng: random.Random,
        admin_user: JasminUser,
        tenant_settings: TenantSettings | None,
        today: date,
    ) -> None:
        min_shares = tenant_settings.min_number_coop_shares if tenant_settings else 3
        value_one_coop_share = (
            tenant_settings.value_one_coop_share if tenant_settings else 100
        )

        candidates = list(
            Subscription.objects.filter(on_waiting_list=False).select_related("member")
        )
        rng.shuffle(candidates)
        chosen = candidates[: int(len(candidates) * 0.65)]

        materialised = failed = 0
        reasons: list[str] = []
        for subscription in chosen:
            member = subscription.member
            # Make the member confirmable: a non-trial, not-yet-confirmed member
            # needs equity within the GenG min/max window, else the member-confirm
            # cascade inside _post_confirm raises MemberCoopSharesOutOfRange.
            self._ensure_member_confirmable(
                member, min_shares, value_one_coop_share, today
            )
            try:
                with transaction.atomic():
                    # Force a clean confirm (the raw flag from seed_demo_members
                    # never materialised anything).
                    subscription.admin_confirmed = False
                    subscription.confirm(admin_user, save=True)
                materialised += 1
            except Exception as exc:  # noqa: BLE001 — seed must not abort on one row
                failed += 1
                if len(reasons) < 5:
                    reasons.append(f"{type(exc).__name__}: {exc}")

        message = (
            f"Materialised {materialised} subscription(s) through confirm() "
            f"(skipped {failed})."
        )
        self.stdout.write(self.style.SUCCESS(message))
        for reason in reasons:
            self.stdout.write(self.style.WARNING(f"  skip: {reason}"))

    def _ensure_member_confirmable(
        self,
        member: Member,
        min_shares: int,
        value_one_coop_share: int,
        today: date,
    ) -> None:
        if member.is_trial or member.admin_confirmed:
            return
        total = CoopShare.objects.filter(
            member=member, cancelled_at__isnull=True
        ).aggregate(total=Sum("amount_of_coop_shares"))["total"] or Decimal("0")
        if total >= min_shares:
            return
        try:
            CoopShare.objects.create(
                member=member,
                amount_of_coop_shares=Decimal(min_shares),
                value_one_coop_share=value_one_coop_share,
                due_date=today - timedelta(days=30),
                paid_at=timezone.now() - timedelta(days=20),
                admin_confirmed=True,
                admin_confirmed_at=timezone.now(),
            )
        except Exception:  # noqa: BLE001 — best effort; confirm() is still guarded
            pass

    # ------------------------------------------------------------------ #
    # 4. Waiting-list cohort
    # ------------------------------------------------------------------ #
    def _seed_waiting_list(self, rng: random.Random, today: date) -> None:
        variations = list(ShareTypeVariation.objects.all())
        cycle = PaymentCycle.objects.filter(choice=PaymentCycleOptions.MONTHLY).first()
        delivery_station_days = list(
            DeliveryStationDay.objects.filter(valid_until__isnull=True)
        )
        members = list(Member.objects.filter(is_active=True)[:50])
        if not (variations and cycle and delivery_station_days and members):
            self.stdout.write(
                self.style.WARNING(
                    "Waiting-list cohort skipped (catalogue / members missing)."
                )
            )
            return

        target = min(5, len(members))
        # Idempotent-ish: don't keep piling up waiting-list rows on re-runs.
        existing = Subscription.objects.filter(on_waiting_list=True).count()
        if existing >= target:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Waiting list: {existing} subscription(s) already queued "
                    "(reused)."
                )
            )
            return

        created = 0
        for member in rng.sample(members, target):
            variation = rng.choice(variations)
            delivery_station_day = rng.choice(delivery_station_days)
            valid_from = _previous_monday(today + timedelta(days=rng.randint(14, 60)))
            valid_until = valid_from + timedelta(days=363)
            reason = rng.choice(
                [
                    Subscription.WaitingListReason.DELIVERY_STATION_FULL,
                    Subscription.WaitingListReason.VARIATION_FULL,
                    Subscription.WaitingListReason.MANUAL,
                ]
            )
            try:
                Subscription.objects.create(
                    member=member,
                    share_type_variation=variation,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    quantity=1,
                    payment_cycle=cycle,
                    default_delivery_station_day=delivery_station_day,
                    on_waiting_list=True,
                    waiting_list_status=Subscription.WaitingListStatus.PENDING,
                    waiting_list_position=created + 1,
                    waiting_list_reason=reason,
                )
                created += 1
            except Exception:  # noqa: BLE001
                continue
        self.stdout.write(
            self.style.SUCCESS(f"Waiting list: {created} subscription(s) queued.")
        )

    # ------------------------------------------------------------------ #
    # 5. SEPA billing profiles
    # ------------------------------------------------------------------ #
    def _seed_billing_profiles(self, rng: random.Random, today: date) -> None:
        confirmed = Member.objects.filter(
            admin_confirmed=True,
            cancelled_at__isnull=True,
            billing_profile__isnull=True,
        )
        created = 0
        for member in confirmed:
            if rng.random() > 0.85:
                continue  # ~15% have no mandate yet (surfaces the "missing SEPA")
            holder = (
                " ".join(p for p in (member.first_name, member.last_name) if p)
                or "Account Holder"
            )
            try:
                BillingProfile.objects.create(
                    member=member,
                    payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
                    iban=TEST_IBAN,
                    account_holder=holder,
                    sepa_mandate_signed_at=today - timedelta(days=rng.randint(30, 400)),
                    is_active=True,
                )
                created += 1
            except Exception:  # noqa: BLE001
                continue
        self.stdout.write(
            self.style.SUCCESS(f"SEPA: {created} billing profile(s) created.")
        )

    # ------------------------------------------------------------------ #
    # 6. Billing run + status variety
    # ------------------------------------------------------------------ #
    def _seed_billing_run(
        self, rng: random.Random, admin_user: JasminUser, today: date
    ) -> None:
        eligible = ChargeSchedule.objects.filter(
            status=ChargeStatus.PLANNED,
            expected_amount__gt=Decimal("0.00"),
            billing_run__isnull=True,
            member__billing_profile__is_active=True,
            member__billing_profile__payment_method=(
                PaymentMethodOptions.SEPA_DIRECT_DEBIT
            ),
        )
        bounds = eligible.aggregate(min_due=Min("due_date"), max_due=Max("due_date"))
        if not bounds["min_due"]:
            self.stdout.write(
                self.style.WARNING(
                    "Billing run skipped: no eligible PLANNED SEPA charges."
                )
            )
            return

        try:
            run = BillingRunService.create_run(
                period_start=bounds["min_due"],
                period_end=bounds["max_due"],
                collection_date=today + timedelta(days=5),
                created_by=admin_user,
            )
            BillingRunService.export(run)
        except (NoEligibleCharges, NoValidSepaMandates, SepaExportInvalid) as exc:
            self.stdout.write(
                self.style.WARNING(f"Billing run skipped: {type(exc).__name__}: {exc}")
            )
            return

        # After export the run's charges are ISSUED. Flip a subset to
        # PAID / PARTIAL / FAILED / WAIVED so per-status totals + the income
        # chart have variety (status is the one mutable column post-issue).
        charge_ids = list(run.charges.values_list("id", flat=True))
        rng.shuffle(charge_ids)
        paid_cut = int(len(charge_ids) * 0.5)
        paid_ids = charge_ids[:paid_cut]
        rest = charge_ids[paid_cut:]
        partial_ids = rest[:3]
        failed_ids = rest[3:5]
        waived_ids = rest[5:7]

        if paid_ids:
            ChargeSchedule.objects.filter(id__in=paid_ids).update(
                status=ChargeStatus.PAID
            )
        if partial_ids:
            ChargeSchedule.objects.filter(id__in=partial_ids).update(
                status=ChargeStatus.PARTIAL
            )
        if failed_ids:
            ChargeSchedule.objects.filter(id__in=failed_ids).update(
                status=ChargeStatus.FAILED
            )
        if waived_ids:
            ChargeSchedule.objects.filter(id__in=waived_ids).update(
                status=ChargeStatus.WAIVED
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Billing run {run.get_display_id()} exported: "
                f"{run.charge_count} charge(s) issued, "
                f"{len(paid_ids)} paid, {len(partial_ids)} partial, "
                f"{len(failed_ids)} failed, {len(waived_ids)} waived."
            )
        )

    # ------------------------------------------------------------------ #
    # 7. Light reseller presence (document pipeline intentionally skipped)
    # ------------------------------------------------------------------ #
    def _seed_resellers(self, tenant_settings: TenantSettings | None) -> None:
        if tenant_settings is not None and not tenant_settings.sells_to_resellers:
            self.stdout.write("Resellers skipped (tenant does not sell to resellers).")
            return

        # name, is_reseller, is_seller, customer_number, (person, street, zip, city)
        reseller_specs = [
            (
                "Green Grocer",
                True,
                True,
                5001,
                ("Anna", "Grün", "Marktstraße 12", "10115", "Berlin"),
            ),
            (
                "Bio Market",
                True,
                False,
                5002,
                ("Bernd", "Bauer", "Bahnhofsplatz 3", "20095", "Hamburg"),
            ),
            (
                "Farm Supplier Co",
                False,
                True,
                5003,
                ("Clara", "Feld", "Feldweg 7", "50667", "Köln"),
            ),
        ]
        created = 0
        for name, is_reseller, is_seller, customer_number, who in reseller_specs:
            if Reseller.objects.filter(customer_number=customer_number).exists():
                continue
            first, last, street, zip_code, city = who
            # A Reseller's address / e-mail / name live on a linked
            # ContactEntity (1:1, and now a REQUIRED FK) — create it first.
            slug = name.lower().replace(" ", "-")
            contact = ContactEntity.objects.create(
                company_name=name,
                first_name=first,
                last_name=last,
                address=street,
                zip_code=zip_code,
                city=city,
                country="Deutschland",
                email=f"kontakt@{slug}.example",
                order_email=f"bestellung@{slug}.example",
                phone=f"+49 30 {customer_number}",
            )
            Reseller.objects.create(
                contact=contact,
                name_for_member_pages=name,
                customer_number=customer_number,
                is_reseller=is_reseller,
                is_active_reseller=is_reseller,
                is_seller=is_seller,
                is_active_seller=is_seller,
            )
            created += 1

        # Wire a couple of purchased/resold articles to a seller so the seller
        # columns render.
        seller = Reseller.objects.filter(is_seller=True).first()
        if seller is not None:
            purchased = list(ShareArticle.objects.filter(is_purchased=True)[:3])
            for article in purchased:
                if article.seller_1_id is None:
                    article.seller_1 = seller
                    article.save(update_fields=["seller_1"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Resellers: {created} created (each with a contact). NOTE: the "
                "reseller DOCUMENT pipeline (offers / orders / delivery notes / "
                "invoices) was NOT seeded — those pages stay empty."
            )
        )

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    def _print_summary(self, tenant: Tenant) -> None:
        materialised_subs = (
            Subscription.objects.filter(admin_confirmed=True, on_waiting_list=False)
            .filter(sharedelivery__isnull=False)
            .distinct()
            .count()
        )
        status_counts = {
            row["status"]: row["n"]
            for row in ChargeSchedule.objects.values("status").annotate(n=Count("id"))
        }
        lines = [
            "",
            f"Reviewer seed complete for tenant '{tenant.schema_name}':",
            f"  Members:              {Member.objects.count()}",
            f"  Subscriptions:        {Subscription.objects.count()} "
            f"(materialised {materialised_subs}, "
            f"waiting-list {Subscription.objects.filter(on_waiting_list=True).count()})",
            f"  ShareDeliveries:      {ShareDelivery.objects.count()}",
            f"  Shares:               {Share.objects.count()}",
            f"  ChargeSchedules:      {ChargeSchedule.objects.count()} "
            f"({', '.join(f'{k}={v}' for k, v in sorted(status_counts.items()))})",
            f"  BillingRuns:          {BillingRun.objects.count()}",
            f"  BillingProfiles:      {BillingProfile.objects.count()}",
            f"  Resellers:            {Reseller.objects.count()}",
            "",
        ]
        self.stdout.write("\n".join(lines))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _previous_monday(d: date) -> date:
    from apps.commissioning.utils.iso_week_utils import previous_monday

    return previous_monday(d)
