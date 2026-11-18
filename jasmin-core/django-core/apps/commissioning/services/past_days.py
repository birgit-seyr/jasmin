"""A harvest, washing or cleaning amount of a day before today is that day's
finished list: a rebuild of the plan neither changes nor removes it, builds no
new one for its source, and builds none for a day before today. Purchases sit on
a fixed day of the delivery week rather than a planned one and always follow the
plan. What a past day's list shows as still in stock, and with it what is left
to harvest, wash or clean, follows the stock as it is recorded, which later
corrections of earlier days still change."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Model, Q, QuerySet
from django.utils import timezone

from ..models.managers import before_day_q
from ..utils.iso_week_utils import week_day_to_date

if TYPE_CHECKING:
    from .theoretical_objects import TheoreticalSourceData


def not_yet_past(queryset: QuerySet) -> QuerySet:
    """The theoretical amounts of ``queryset`` from today on, the ones a
    rebuild may replace."""
    return queryset.exclude(before_day_q(timezone.localdate()))


class PastDays:
    """What a build of ``sources`` leaves out: a harvest, washing or cleaning
    amount of a day before today, and one for a source that still has one.
    ``models`` names the theoretical model of each kind of amount."""

    def __init__(
        self, sources: list[TheoreticalSourceData], models: dict[str, type[Model]]
    ) -> None:
        self.today = timezone.localdate()
        self.planned = {
            key: self._sources_with(model, sources) for key, model in models.items()
        }

    @staticmethod
    def _sources_with(model: type[Model], sources: list[TheoreticalSourceData]) -> set:
        """The sources that already have an amount of ``model``: once a rebuild
        has cleared the rest, one of a day before today."""
        share_content_ids = [s.share_content.pk for s in sources if s.share_content]
        order_content_ids = [s.order_content.pk for s in sources if s.order_content]
        if not share_content_ids and not order_content_ids:
            return set()
        rows = model._default_manager.filter(
            Q(share_content_id__in=share_content_ids)
            | Q(order_content_id__in=order_content_ids)
        ).values_list("share_content_id", "order_content_id")
        return {
            (
                ("share_content", share_content_id)
                if share_content_id
                else ("order_content", order_content_id)
            )
            for share_content_id, order_content_id in rows
        }

    def leave_out(self, key: str, src: TheoreticalSourceData, theoretical: Any) -> bool:
        day = week_day_to_date(
            theoretical.year, theoretical.delivery_week, theoretical.day_number
        )
        return day < self.today or src.source_key in self.planned[key]
