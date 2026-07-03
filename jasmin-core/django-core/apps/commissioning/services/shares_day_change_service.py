"""Service for changing day fields on Share rows for a given week.

Updating ``harvesting_day`` / ``washing_day`` / ``cleaning_day`` /
``packing_day`` on a Share invalidates any theoretical objects and
movements that were derived from it (those snapshot the day at creation
time). This service:

1. Locks the affected Share rows for the duration of the transaction.
2. Optionally rejects past weeks (today or earlier).
3. Applies the requested field changes via ``share.save()`` so the
   model's default-fill logic still runs.
4. If any *recompute-relevant* day field changed, deletes the existing
   theoretical objects and SHARECONTENT movements for the affected
   ShareContents (cascade removes their is_theoretical movements) and
   re-creates them from the new source-of-truth.

All work happens inside one ``transaction.atomic`` block.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from isoweek import Week

from core.errors import BadRequestError

from ..errors import PastWeekError
from ..models import (
    Share,
)

# Fields that may be updated via this service.
SHARE_DAY_FIELDS: tuple[str, ...] = (
    "changed_day_number",
    "harvesting_day",
    "packing_day",
    "washing_day",
    "cleaning_day",
    "get_current_stock_day",
)

# Subset whose change requires regeneration of theoretical objects /
# movements. ``changed_day_number`` and ``get_current_stock_day`` are
# currently informational only and do not feed the theoretical/movement
# pipelines, so changing them does NOT trigger a rebuild.
RECOMPUTE_RELEVANT_FIELDS: frozenset[str] = frozenset(
    {"harvesting_day", "packing_day", "washing_day", "cleaning_day"}
)


class SharesDayChangeService:
    """Apply day-field updates to Share rows for one week."""

    @staticmethod
    @transaction.atomic
    def apply(
        *,
        year: int,
        delivery_week: int,
        data: dict[str, Any],
        day_number: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Apply *data* to the matching Share rows.

        Args:
            year, delivery_week: ISO year/week selector.
            data: Mapping of field name -> new value. Only keys in
                :data:`SHARE_DAY_FIELDS` are honoured. Sentinel value
                ``"undefined"`` is treated as ``None``.
            day_number: If given, only Shares whose
                ``delivery_day.day_number`` equals this are affected.
            force: When True, allow mutating past weeks.

        Returns:
            A dict with ``updated_share_ids``, ``recomputed_share_content_ids``
            and ``changed_fields`` for diagnostics / tests.

        Raises:
            PastWeekError: when the week is in the past and
                ``force=False``.
            ValueError: on missing required arguments.
        """
        if year is None or delivery_week is None:
            raise BadRequestError(
                "year and delivery_week are required",
                code="shares_day_change.missing_required",
            )

        # ── Past-week guard ──
        if not force:
            today = timezone.now().date()
            week_monday = Week(int(year), int(delivery_week)).monday()
            if week_monday <= today:
                raise PastWeekError(
                    f"Refusing to modify shares for past/current week "
                    f"{delivery_week}/{year} (starts {week_monday}). "
                    "Pass force=True to override."
                )

        # ── Filter relevant incoming fields & normalise sentinels ──
        cleaned: dict[str, Any] = {}
        for field in SHARE_DAY_FIELDS:
            if field in data:
                value = data[field]
                cleaned[field] = None if value in ("undefined", None) else value

        # ── Lock & fetch shares ──
        # Lock in deterministic (id) order so a concurrent day-change can't
        # AB/BA-deadlock against an id-ordered recompute (share_content_service)
        # on an overlapping Share set.
        shares_qs = (
            Share.objects.select_for_update()
            .filter(year=year, delivery_week=delivery_week)
            .select_related("delivery_day")
            .order_by("id")
        )
        if day_number is not None:
            shares_qs = shares_qs.filter(delivery_day__day_number=int(day_number))

        shares = list(shares_qs)
        if not shares:
            return {
                "updated_share_ids": [],
                "recomputed_share_content_ids": [],
                "changed_fields": [],
            }

        # ── Detect actual changes (so we don't recompute unnecessarily) ──
        changed_fields: set[str] = set()
        for share in shares:
            for field, new_value in cleaned.items():
                if getattr(share, field) != new_value:
                    changed_fields.add(field)

        if not changed_fields:
            return {
                "updated_share_ids": [s.id for s in shares],
                "recomputed_share_content_ids": [],
                "changed_fields": [],
            }

        # ── Apply changes & save (per-instance, so model save() runs) ──
        for share in shares:
            for field in changed_fields:
                setattr(share, field, cleaned[field])
            share.save()

        # ── Decide whether to recompute theoreticals / movements ──
        needs_recompute = bool(changed_fields & RECOMPUTE_RELEVANT_FIELDS)

        recomputed_share_content_ids: list[Any] = []
        if needs_recompute:
            recomputed_share_content_ids = SharesDayChangeService._recompute_for_shares(
                shares
            )

        # MEM-3: changed_day_number is the top-priority input to
        # share_delivery_date(), which the billing-regen uses to bucket
        # deliveries into periods — so a day shift can move/drop a billable
        # delivery. It's NOT in RECOMPUTE_RELEVANT_FIELDS (no theoretical impact),
        # but it DOES change the billable set, so re-plan affected subscriptions.
        # Deferred import (one-way commissioning→shared seam); a hook exception
        # propagating rolls back this whole atomic day change — correct.
        if "changed_day_number" in changed_fields:
            from apps.shared.subscription_hooks import notify_subscription_changed

            from ..models import ShareDelivery

            subscriptions = {
                sd.subscription
                for sd in ShareDelivery.objects.filter(share__in=shares).select_related(
                    "subscription"
                )
                if sd.subscription_id is not None
            }
            for subscription in subscriptions:
                notify_subscription_changed(subscription)

        return {
            "updated_share_ids": [s.id for s in shares],
            "recomputed_share_content_ids": recomputed_share_content_ids,
            "changed_fields": sorted(changed_fields),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_for_shares(shares: list[Share]) -> list[Any]:
        """Recompute theoreticals/movements via the canonical ``recompute_shares``
        wrapper, so a virtual variation's dependent physical shares are recomputed
        too (the virtual→physical expansion every other caller gets). Day-change
        only mutates day fields today, so the expansion is a no-op, but a future
        demand-relevant edit here would otherwise silently miss those shares.
        Returns the touched ``ShareContent`` ids."""
        # Local import to avoid an import cycle at app-load time.
        from .recompute import recompute_shares

        return recompute_shares([share.id for share in shares])
