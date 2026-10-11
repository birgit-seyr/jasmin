"""Planning slots and their share option.

A planning page lists one share option, and an article can belong to three
(``share_option``, ``share_option2``, ``share_option3``), so a slot — one
article in one unit and size — is planned per option, and every write to it
stays inside its option.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import astuple, dataclass
from typing import Any, ClassVar, TypeVar

from django.db.models import Model, Q, QuerySet

from ..errors import CompositeIdInvalid, ShareContentError
from ..models import ShareContent, ShareTypeVariation
from ..models.choices import UnitOptions, VegetableSizeOptions
from ..utils.composite_id_utils import parse_slot_id

_ModelT = TypeVar("_ModelT", bound=Model)


def in_share_option(
    queryset: QuerySet[_ModelT], share_option: str | None, *, variation: str
) -> QuerySet[_ModelT]:
    """``queryset`` narrowed to ``share_option``, reached through the share
    type variation at ``variation``; all of it for no option."""
    if share_option is None:
        return queryset
    return queryset.filter(**{f"{variation}__share_type__share_option": share_option})


def refuse_variations_outside(
    share_option: str | None, variation_ids: Iterable[str]
) -> None:
    """Refuse amounts for variations of another share option than the slot's:
    the slot is rebuilt from its payload, so they would land in that option's
    plan. A slot of every option takes any variation."""
    if share_option is None:
        return
    outside = sorted(
        ShareTypeVariation.objects.filter(id__in=set(variation_ids))
        .exclude(share_type__share_option=share_option)
        .values_list("id", flat=True)
    )
    if outside:
        raise ShareContentError(
            f"Amounts for variations {outside} belong to another share option "
            f"than {share_option}.",
            code="share_content.variation_outside_share_option",
            details={"variation_ids": outside, "share_option": share_option},
        )


@dataclass(frozen=True)
class PlanningSlot:
    """A week's slot on the planning grid: one article in one unit and size,
    in one share option, or in every option when ``share_option`` is None."""

    year: int
    delivery_week: int
    share_article_id: str
    unit: str
    size: str
    share_option: str | None = None

    _ID_FIELDS: ClassVar[list[tuple[str, Any]]] = [
        ("year", int),
        ("delivery_week", int),
        ("share_article_id", str),
        ("unit", str),
        ("size", str),
    ]

    @classmethod
    def parse(cls, raw: str | None, *, code: str) -> PlanningSlot:
        """The slot a grid row's id names; ``CompositeIdInvalid`` with
        ``code`` for a malformed one."""
        return cls(**parse_slot_id(raw, fields=cls._ID_FIELDS, code=code))

    def refuse_unknown_unit_or_size(self, *, code: str) -> None:
        """Refuse a unit or size its column doesn't allow, which the id carries
        unchecked into rows that ``bulk_create`` doesn't validate. Only a write
        that builds rows from the slot needs this: reads, deletes and finalizing
        match the stored rows by their unit and size."""
        if self.unit not in UnitOptions.values:
            raise CompositeIdInvalid(f"Invalid unit {self.unit!r} in id.", code=code)
        if self.size not in VegetableSizeOptions.values:
            raise CompositeIdInvalid(f"Invalid size {self.size!r} in id.", code=code)

    @property
    def key(self) -> tuple[Any, ...]:
        return astuple(self)

    def share_contents_q(self) -> Q:
        """The filter for the slot's share contents."""
        slot_q = Q(
            share__year=self.year,
            share__delivery_week=self.delivery_week,
            share_article_id=self.share_article_id,
            unit=self.unit,
            size=self.size,
        )
        if self.share_option is None:
            return slot_q
        return slot_q & Q(
            share__share_type_variation__share_type__share_option=self.share_option
        )

    def share_contents(self) -> QuerySet[ShareContent]:
        return ShareContent.objects.filter(self.share_contents_q())

    def refuse_cells_outside(self, day_variations: Iterable[tuple[Any, ...]]) -> None:
        """Refuse planned cells — ``(day, variation, …)`` tuples — whose
        variation belongs to another share option than the slot's."""
        refuse_variations_outside(
            self.share_option, (cell[1] for cell in day_variations)
        )
