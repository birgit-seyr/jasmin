"""Single entry point for "how many share_type_variations do we need?".

This is the *port* in the hexagonal sense. Two adapters back it:

* :class:`SubscriptionDemandBackend` — derives counts from the in-app
  ``Subscription`` / ``ShareDelivery`` rows. Used by tenants that run the
  full member/abo flow.
* :class:`ExternalDemandBackend` — reads aggregated counts from
  :class:`ExternalShareDemand`, populated by the weekly CSV import.

Which backend a tenant uses is decided by the existing TenantSettings
flag ``uploads_weekly_share_amount`` (already exposed in
``ConfigurationCommissioning`` under "Planning & Management"):

* ``False`` (default) → ``SubscriptionDemandBackend``
* ``True``  → ``ExternalDemandBackend``

Refactor downstream services (forecast, stock, packing, …) to call this
service instead of querying ``ShareDelivery`` / ``Subscription`` directly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

from django.db import connection
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import (
    CapacityReservation,
    ExternalShareDemand,
    Share,
    ShareDelivery,
)

# --- public DTO -------------------------------------------------------------


DemandByVariation = dict[str, int]  # {variation_id: qty}
DemandByStation = dict[str, int]  # {delivery_station_id: qty}
DemandByStationDay = dict[str, int]  # {delivery_station_day_id: qty}


# --- backends ---------------------------------------------------------------


class _DemandBackend(Protocol):
    def quantity_for_share(self, share: Share) -> int: ...

    def quantity_by_station(self, share: Share) -> DemandByStation: ...

    def variation_totals(self, year: int, delivery_week: int) -> DemandByVariation: ...

    def quantity_for_station_day(
        self,
        *,
        station_day_id: str,
        year: int,
        delivery_week: int,
        variation_id: str,
    ) -> int: ...

    def aggregated_rows(
        self,
        *,
        year: int | None = None,
        delivery_week: int | None = None,
        delivery_weeks: Iterable[int] | None = None,
        delivery_day_id: str | None = None,
        delivery_day_ids: Iterable[str] | None = None,
        variation_id: str | None = None,
        variation_ids: Iterable[str] | None = None,
        delivery_station_id: str | None = None,
        tour_number: int | None = None,
        joker: bool | None = False,
        donation_joker: bool | None = False,
    ) -> list[dict]: ...

    def share_option_capacity_count(
        self,
        *,
        delivery_station_day_id: str,
        year: int,
        delivery_week: int,
    ) -> int: ...

    def capacity_counts_by_week(
        self,
        *,
        station_day_ids: Iterable[str],
        year_weeks: Iterable[tuple[int, int]],
    ) -> dict[tuple[str, int, int], int]: ...

    def peak_occupied_from_week(
        self,
        *,
        delivery_station_day_id: str,
        from_year: int,
        from_week: int,
    ) -> tuple[int, int | None, int | None]: ...


class SubscriptionDemandBackend:
    """Aggregates over ``ShareDelivery`` (the existing model)."""

    def quantity_for_share(self, share: Share) -> int:
        return (
            ShareDelivery.objects.filter(share=share)
            .filter(ShareDelivery.delivery_counts_q())
            .aggregate(n=Sum("subscription__quantity"))
            .get("n")
            or 0
        )

    def quantity_by_station(self, share: Share) -> DemandByStation:
        rows = (
            ShareDelivery.objects.filter(share=share)
            .filter(ShareDelivery.delivery_counts_q())
            .values("delivery_station_day__delivery_station_id")
            .annotate(n=Sum("subscription__quantity"))
        )
        out: DemandByStation = {}
        for r in rows:
            station_id = r["delivery_station_day__delivery_station_id"]
            if station_id is None:
                continue
            out[station_id] = int(r["n"] or 0)
        return out

    def variation_totals(self, year: int, delivery_week: int) -> DemandByVariation:
        rows = (
            ShareDelivery.objects.filter(
                share__year=year,
                share__delivery_week=delivery_week,
            )
            .filter(ShareDelivery.delivery_counts_q())
            .values("share__share_type_variation_id")
            .annotate(n=Sum("subscription__quantity"))
        )
        return {
            r["share__share_type_variation_id"]: int(r["n"] or 0)
            for r in rows
            if r["share__share_type_variation_id"]
        }

    def quantity_for_station_day(
        self,
        *,
        station_day_id: str,
        year: int,
        delivery_week: int,
        variation_id: str,
    ) -> int:
        return (
            ShareDelivery.objects.filter(
                delivery_station_day_id=station_day_id,
                share__year=year,
                share__delivery_week=delivery_week,
                share__share_type_variation_id=variation_id,
            )
            .filter(ShareDelivery.delivery_counts_q())
            .aggregate(n=Sum("subscription__quantity"))
            .get("n")
            or 0
        )

    def aggregated_rows(
        self,
        *,
        year: int | None = None,
        delivery_week: int | None = None,
        delivery_weeks: Iterable[int] | None = None,
        delivery_day_id: str | None = None,
        delivery_day_ids: Iterable[str] | None = None,
        variation_id: str | None = None,
        variation_ids: Iterable[str] | None = None,
        delivery_station_id: str | None = None,
        tour_number: int | None = None,
        joker: bool | None = False,
        donation_joker: bool | None = False,
    ) -> list[dict]:
        """Return rows aggregated by ``(week, day, variation, station_day,
        tour, station)``.

        ``joker`` / ``donation_joker``: each a tri-state — ``False`` (default)
        excludes, ``True`` selects only-those, ``None`` includes both. Production
        demand uses the defaults (both excluded — a donation joker is billed but
        not grown/packed); the donation report passes ``donation_joker=True`` to
        get only the donatable boxes. ``delivery_weeks`` lets recompute-style
        callers fetch a whole season in ONE query instead of one per week;
        rows always carry ``delivery_week`` so callers can split them.
        """
        qs = ShareDelivery.objects.all()
        if year is not None:
            qs = qs.filter(share__year=year)
        if delivery_week is not None:
            qs = qs.filter(share__delivery_week=delivery_week)
        if delivery_weeks is not None:
            qs = qs.filter(share__delivery_week__in=list(delivery_weeks))
        if delivery_day_id is not None:
            qs = qs.filter(share__delivery_day_id=delivery_day_id)
        if delivery_day_ids is not None:
            qs = qs.filter(share__delivery_day_id__in=list(delivery_day_ids))
        if variation_id is not None:
            qs = qs.filter(subscription__share_type_variation_id=(variation_id))
        if variation_ids is not None:
            qs = qs.filter(
                subscription__share_type_variation_id__in=list(variation_ids)
            )
        if delivery_station_id is not None:
            qs = qs.filter(
                delivery_station_day__delivery_station_id=delivery_station_id
            )
        if tour_number is not None:
            qs = qs.filter(delivery_station_day__tour_number=tour_number)
        if joker is True:
            qs = qs.filter(joker_taken=True)
        elif joker is False:
            qs = qs.exclude(joker_taken=True)

        # Donation jokers are billed but NOT produced, so production demand
        # excludes them by default — they must not inflate theoreticals,
        # movements, packing, or share_type_variation amounts. ``True`` selects
        # ONLY them (the donation report).
        if donation_joker is True:
            qs = qs.filter(donation_joker_taken=True)
        elif donation_joker is False:
            qs = qs.exclude(donation_joker_taken=True)

        # On-off opt-outs never ship → drop them from production demand. (Joker
        # is handled separately above via the tri-state ``joker`` param.)
        qs = qs.exclude(ShareDelivery.opted_out_q())

        # Group by the *share*'s variation, not the subscription's. Using the
        # share path ensures a row appears even when no subscription is
        # attached (e.g. test fixtures or legacy data); when a subscription is
        # attached, the variation is identical to the one reached directly via
        # the subscription.
        rows = qs.values(
            "share__delivery_week",
            "share__delivery_day_id",
            "share__share_type_variation_id",
            "delivery_station_day_id",
            "delivery_station_day__tour_number",
            "delivery_station_day__delivery_station_id",
        ).annotate(count=Sum("subscription__quantity"))

        return [
            {
                "delivery_week": r["share__delivery_week"],
                "day_id": r["share__delivery_day_id"],
                "variation_id": r["share__share_type_variation_id"],
                "station_day_id": r["delivery_station_day_id"],
                "tour_number": r["delivery_station_day__tour_number"],
                "station_id": r["delivery_station_day__delivery_station_id"],
                "count": int(r["count"] or 0),
            }
            for r in rows
        ]

    def share_option_capacity_count(
        self,
        *,
        delivery_station_day_id: str,
        year: int,
        delivery_week: int,
    ) -> int:
        # Capacity is in SHARES, so weight by subscription quantity (a
        # quantity=3 subscription occupies 3 slots), matching this backend's
        # quantity_for_station_day, the external backend, and the
        # DeliveryStationDay.capacity docstring. Counting rows under-occupied
        # multi-quantity subscriptions and let a capped station-day overfill.
        # BL-5: occupancy must use the SAME "this delivery actually ships"
        # predicate as demand — a jokered (joker_taken) or opted-out delivery
        # does not ship that week and must not consume a physical pickup slot,
        # else a capped station-day reports phantom occupancy and falsely
        # rejects new subscribers/moves. Mirrors the demand methods above.
        deliveries = (
            ShareDelivery.objects.filter(
                delivery_station_day_id=delivery_station_day_id,
                share__year=year,
                share__delivery_week=delivery_week,
                share__share_type_variation__share_type__is_additional_share_type=False,
            )
            .filter(ShareDelivery.delivery_counts_q())
            .aggregate(n=Sum(Coalesce("subscription__quantity", 1)))["n"]
            or 0
        )
        # Active draft reservations also hold a slot (see CapacityReservation),
        # weighted by their subscription's quantity for the same reason.
        reservations = (
            CapacityReservation.objects.filter(
                delivery_station_day_id=delivery_station_day_id,
                year=year,
                week=delivery_week,
                expires_at__gt=timezone.now(),
            ).aggregate(n=Sum(Coalesce("subscription__quantity", 1)))["n"]
            or 0
        )
        return deliveries + reservations

    def capacity_counts_by_week(
        self,
        *,
        station_day_ids: Iterable[str],
        year_weeks: Iterable[tuple[int, int]],
    ) -> dict[tuple[str, int, int], int]:
        # Batched form of ``share_option_capacity_count`` over many
        # station-days and weeks at once — ONE grouped query instead of a
        # ``.count()`` per (station_day, week). Used by the serializer to
        # kill the capacity-by-week N+1.
        ids = list(station_day_ids)
        wanted = set(year_weeks)
        if not ids or not wanted:
            return {}
        years = {year for year, _ in wanted}
        weeks = {week for _, week in wanted}
        rows = (
            ShareDelivery.objects.filter(
                delivery_station_day_id__in=ids,
                share__year__in=years,
                share__delivery_week__in=weeks,
                share__share_type_variation__share_type__is_additional_share_type=False,
            )
            # BL-5: jokered/opted-out don't ship — the ONE canonical predicate.
            .filter(ShareDelivery.delivery_counts_q())
            .values(
                "delivery_station_day_id",
                "share__year",
                "share__delivery_week",
            )
            .annotate(count=Sum(Coalesce("subscription__quantity", 1)))
        )
        out: dict[tuple[str, int, int], int] = {}
        for row in rows:
            year_week = (row["share__year"], row["share__delivery_week"])
            if year_week in wanted:
                out[(row["delivery_station_day_id"], *year_week)] = int(
                    row["count"] or 0
                )

        # Add active draft reservations (one more grouped query).
        reservation_rows = (
            CapacityReservation.objects.filter(
                delivery_station_day_id__in=ids,
                year__in=years,
                week__in=weeks,
                expires_at__gt=timezone.now(),
            )
            .values("delivery_station_day_id", "year", "week")
            .annotate(count=Sum(Coalesce("subscription__quantity", 1)))
        )
        for row in reservation_rows:
            year_week = (row["year"], row["week"])
            if year_week in wanted:
                key = (row["delivery_station_day_id"], *year_week)
                out[key] = out.get(key, 0) + int(row["count"] or 0)
        return out

    def peak_occupied_from_week(
        self,
        *,
        delivery_station_day_id: str,
        from_year: int,
        from_week: int,
    ) -> tuple[int, int | None, int | None]:
        # Busiest single week at/after (from_year, from_week): confirmed
        # deliveries + active draft reservations, merged per week. ISO
        # (year, week) tuple comparison via the OR-Q (year>Y, or year==Y &&
        # week>=W) — past weeks are excluded (immutable, can't constrain a cap).
        per_week: dict[tuple[int, int], int] = defaultdict(int)

        future_deliveries = Q(share__year__gt=from_year) | Q(
            share__year=from_year, share__delivery_week__gte=from_week
        )
        delivery_rows = (
            ShareDelivery.objects.filter(
                delivery_station_day_id=delivery_station_day_id,
                share__share_type_variation__share_type__is_additional_share_type=False,
            )
            .filter(future_deliveries)
            # BL-5: jokered/opted-out don't ship — the ONE canonical predicate.
            .filter(ShareDelivery.delivery_counts_q())
            .values("share__year", "share__delivery_week")
            .annotate(count=Sum(Coalesce("subscription__quantity", 1)))
        )
        for row in delivery_rows:
            per_week[(row["share__year"], row["share__delivery_week"])] += int(
                row["count"] or 0
            )

        future_reservations = Q(year__gt=from_year) | Q(
            year=from_year, week__gte=from_week
        )
        reservation_rows = (
            CapacityReservation.objects.filter(
                delivery_station_day_id=delivery_station_day_id,
                expires_at__gt=timezone.now(),
            )
            .filter(future_reservations)
            .values("year", "week")
            .annotate(count=Sum(Coalesce("subscription__quantity", 1)))
        )
        for row in reservation_rows:
            per_week[(row["year"], row["week"])] += int(row["count"] or 0)

        if not per_week:
            return (0, None, None)
        (peak_year, peak_week), peak = max(per_week.items(), key=lambda kv: kv[1])
        return (peak, peak_year, peak_week)


class ExternalDemandBackend:
    """Aggregates over ``ExternalShareDemand`` (CSV-imported)."""

    def quantity_for_share(self, share: Share) -> int:
        return (
            ExternalShareDemand.objects.filter(
                year=share.year,
                delivery_week=share.delivery_week,
                share_type_variation_id=share.share_type_variation_id,
                delivery_station_day__delivery_day_id=share.delivery_day_id,
            )
            .aggregate(n=Sum("quantity"))
            .get("n")
            or 0
        )

    def quantity_by_station(self, share: Share) -> DemandByStation:
        rows = (
            ExternalShareDemand.objects.filter(
                year=share.year,
                delivery_week=share.delivery_week,
                share_type_variation_id=share.share_type_variation_id,
                delivery_station_day__delivery_day_id=share.delivery_day_id,
            )
            .values("delivery_station_day__delivery_station_id")
            .annotate(n=Sum("quantity"))
        )
        out: DemandByStation = defaultdict(int)
        for r in rows:
            station_id = r["delivery_station_day__delivery_station_id"]
            if station_id is None:
                continue
            out[station_id] += int(r["n"] or 0)
        return dict(out)

    def variation_totals(self, year: int, delivery_week: int) -> DemandByVariation:
        rows = (
            ExternalShareDemand.objects.filter(year=year, delivery_week=delivery_week)
            .values("share_type_variation_id")
            .annotate(n=Sum("quantity"))
        )
        return {r["share_type_variation_id"]: int(r["n"] or 0) for r in rows}

    def quantity_for_station_day(
        self,
        *,
        station_day_id: str,
        year: int,
        delivery_week: int,
        variation_id: str,
    ) -> int:
        return (
            ExternalShareDemand.objects.filter(
                year=year,
                delivery_week=delivery_week,
                delivery_station_day_id=station_day_id,
                share_type_variation_id=variation_id,
            )
            .aggregate(n=Sum("quantity"))
            .get("n")
            or 0
        )

    def aggregated_rows(
        self,
        *,
        year: int | None = None,
        delivery_week: int | None = None,
        delivery_weeks: Iterable[int] | None = None,
        delivery_day_id: str | None = None,
        delivery_day_ids: Iterable[str] | None = None,
        variation_id: str | None = None,
        variation_ids: Iterable[str] | None = None,
        delivery_station_id: str | None = None,
        tour_number: int | None = None,
        joker: bool | None = False,
        donation_joker: bool | None = False,
    ) -> list[dict]:
        # CSV imports carry neither joker nor donation-joker information; if the
        # caller asks for "only (donation) jokers" return an empty result.
        if joker is True or donation_joker is True:
            return []

        qs = ExternalShareDemand.objects.all()
        if year is not None:
            qs = qs.filter(year=year)
        if delivery_week is not None:
            qs = qs.filter(delivery_week=delivery_week)
        if delivery_weeks is not None:
            qs = qs.filter(delivery_week__in=list(delivery_weeks))
        if delivery_day_id is not None:
            qs = qs.filter(delivery_station_day__delivery_day_id=delivery_day_id)
        if delivery_day_ids is not None:
            qs = qs.filter(
                delivery_station_day__delivery_day_id__in=list(delivery_day_ids)
            )
        if variation_id is not None:
            qs = qs.filter(share_type_variation_id=variation_id)
        if variation_ids is not None:
            qs = qs.filter(share_type_variation_id__in=list(variation_ids))
        if delivery_station_id is not None:
            qs = qs.filter(
                delivery_station_day__delivery_station_id=delivery_station_id
            )
        if tour_number is not None:
            qs = qs.filter(delivery_station_day__tour_number=tour_number)

        rows = qs.values(
            "delivery_week",
            "delivery_station_day__delivery_day_id",
            "share_type_variation_id",
            "delivery_station_day_id",
            "delivery_station_day__tour_number",
            "delivery_station_day__delivery_station_id",
        ).annotate(count=Sum("quantity"))

        return [
            {
                "delivery_week": r["delivery_week"],
                "day_id": r["delivery_station_day__delivery_day_id"],
                "variation_id": r["share_type_variation_id"],
                "station_day_id": r["delivery_station_day_id"],
                "tour_number": r["delivery_station_day__tour_number"],
                "station_id": r["delivery_station_day__delivery_station_id"],
                "count": int(r["count"] or 0),
            }
            for r in rows
        ]

    def share_option_capacity_count(
        self,
        *,
        delivery_station_day_id: str,
        year: int,
        delivery_week: int,
    ) -> int:
        # CSV demand carries quantities, so "capacity used" is the sum of
        # quantities of variations belonging to the requested share options.
        return (
            ExternalShareDemand.objects.filter(
                delivery_station_day_id=delivery_station_day_id,
                year=year,
                delivery_week=delivery_week,
                share_type_variation__share_type__is_additional_share_type=False,
            )
            .aggregate(n=Sum("quantity"))
            .get("n")
            or 0
        )

    def capacity_counts_by_week(
        self,
        *,
        station_day_ids: Iterable[str],
        year_weeks: Iterable[tuple[int, int]],
    ) -> dict[tuple[str, int, int], int]:
        # CSV demand carries quantities, so "used" is the summed quantity.
        # One grouped query for all station-days/weeks (mirrors the
        # subscription backend's batched form).
        ids = list(station_day_ids)
        wanted = set(year_weeks)
        if not ids or not wanted:
            return {}
        years = {year for year, _ in wanted}
        weeks = {week for _, week in wanted}
        rows = (
            ExternalShareDemand.objects.filter(
                delivery_station_day_id__in=ids,
                year__in=years,
                delivery_week__in=weeks,
                share_type_variation__share_type__is_additional_share_type=False,
            )
            .values("delivery_station_day_id", "year", "delivery_week")
            .annotate(n=Sum("quantity"))
        )
        out: dict[tuple[str, int, int], int] = {}
        for row in rows:
            year_week = (row["year"], row["delivery_week"])
            if year_week in wanted:
                out[(row["delivery_station_day_id"], *year_week)] = int(row["n"] or 0)
        return out

    def peak_occupied_from_week(
        self,
        *,
        delivery_station_day_id: str,
        from_year: int,
        from_week: int,
    ) -> tuple[int, int | None, int | None]:
        # CSV demand carries quantities, so the busiest week is the highest
        # summed quantity at/after (from_year, from_week).
        future = Q(year__gt=from_year) | Q(year=from_year, delivery_week__gte=from_week)
        rows = (
            ExternalShareDemand.objects.filter(
                delivery_station_day_id=delivery_station_day_id,
                share_type_variation__share_type__is_additional_share_type=False,
            )
            .filter(future)
            .values("year", "delivery_week")
            .annotate(n=Sum("quantity"))
        )
        peak, peak_year, peak_week = 0, None, None
        for row in rows:
            n = int(row["n"] or 0)
            if n > peak:
                peak, peak_year, peak_week = n, row["year"], row["delivery_week"]
        return (peak, peak_year, peak_week)


# --- dispatcher -------------------------------------------------------------


def _resolve_backend() -> _DemandBackend:
    """Pick the backend based on the *current* tenant's settings.

    Reads ``TenantSettings.uploads_weekly_share_amount`` for the current
    tenant (set via the existing Configuration → Commissioning →
    Planning & Management UI).
    """
    # Local import to keep this app loosely coupled from the tenants app.
    from apps.shared.tenants.models import Tenant, TenantSettings

    # On the Huey worker (deferred recompute), ``connection.tenant`` under
    # ``schema_context`` is a django-tenants FakeTenant, NOT a real Tenant row —
    # ``get_current_settings(FakeTenant)`` then filters a CharField-PK FK against
    # a non-Model and matches nothing, silently falling back to the subscription
    # backend and WIPING an external-CSV tenant's theoreticals. Resolve the real
    # Tenant by schema_name (the payments ``_current_tenant`` pattern) so the
    # deferred path picks the same backend as every request-context call.
    tenant = getattr(connection, "tenant", None)
    if not isinstance(tenant, Tenant):
        tenant = Tenant.objects.filter(schema_name=connection.schema_name).first()
    if tenant is not None:
        settings = TenantSettings.get_current_settings(tenant)
        if settings and getattr(settings, "uploads_weekly_share_amount", False):
            return ExternalDemandBackend()
    return SubscriptionDemandBackend()


class ShareDemandService:
    """Façade. All callers go through these classmethods."""

    @classmethod
    def quantity_for_share(cls, share: Share) -> int:
        return _resolve_backend().quantity_for_share(share)

    @classmethod
    def quantity_by_station(cls, share: Share) -> DemandByStation:
        return _resolve_backend().quantity_by_station(share)

    @classmethod
    def variation_totals(cls, year: int, delivery_week: int) -> DemandByVariation:
        return _resolve_backend().variation_totals(year, delivery_week)

    @classmethod
    def quantity_for_station_day(
        cls,
        *,
        station_day_id: str,
        year: int,
        delivery_week: int,
        variation_id: str,
    ) -> int:
        return _resolve_backend().quantity_for_station_day(
            station_day_id=station_day_id,
            year=year,
            delivery_week=delivery_week,
            variation_id=variation_id,
        )

    @classmethod
    def aggregated_rows(
        cls,
        *,
        year: int | None = None,
        delivery_week: int | None = None,
        delivery_weeks: Iterable[int] | None = None,
        delivery_day_id: str | None = None,
        delivery_day_ids: Iterable[str] | None = None,
        variation_id: str | None = None,
        variation_ids: Iterable[str] | None = None,
        delivery_station_id: str | None = None,
        tour_number: int | None = None,
        joker: bool | None = False,
        donation_joker: bool | None = False,
    ) -> list[dict]:
        return _resolve_backend().aggregated_rows(
            year=year,
            delivery_week=delivery_week,
            delivery_weeks=delivery_weeks,
            delivery_day_id=delivery_day_id,
            delivery_day_ids=delivery_day_ids,
            variation_id=variation_id,
            variation_ids=variation_ids,
            delivery_station_id=delivery_station_id,
            tour_number=tour_number,
            joker=joker,
            donation_joker=donation_joker,
        )

    @classmethod
    def share_option_capacity_count(
        cls,
        *,
        delivery_station_day_id: str,
        year: int,
        delivery_week: int,
    ) -> int:
        return _resolve_backend().share_option_capacity_count(
            delivery_station_day_id=delivery_station_day_id,
            year=year,
            delivery_week=delivery_week,
        )

    @classmethod
    def capacity_counts_by_week(
        cls,
        *,
        station_day_ids: Iterable[str],
        year_weeks: Iterable[tuple[int, int]],
    ) -> dict[tuple[str, int, int], int]:
        """Batched occupancy: ``{(station_day_id, year, week): used}``.

        One grouped query for the whole ``(station_day_ids × year_weeks)``
        grid, so capacity-by-week serialization is a single query instead
        of one ``.count()`` per week per row.
        """
        return _resolve_backend().capacity_counts_by_week(
            station_day_ids=station_day_ids,
            year_weeks=year_weeks,
        )

    @classmethod
    def peak_occupied_from_week(
        cls,
        *,
        delivery_station_day_id: str,
        from_year: int,
        from_week: int,
    ) -> tuple[int, int | None, int | None]:
        """Busiest single week at/after ``(from_year, from_week)`` for one
        station-day: ``(peak_occupied, peak_year, peak_week)``.

        Used to floor a manual capacity edit — the office can't lower a
        station-day's cap below the most-booked upcoming week.
        """
        return _resolve_backend().peak_occupied_from_week(
            delivery_station_day_id=delivery_station_day_id,
            from_year=from_year,
            from_week=from_week,
        )
