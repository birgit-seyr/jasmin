from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.apps import apps
from django.db.models import Model, QuerySet

from ..errors import CompositeIdInvalid
from ..models.mixin import FinalizableMixin


def parse_composite_pk(
    raw: str,
    *,
    fields: list[tuple[str, Callable[[str], Any]]],
    code: str,
) -> dict[str, Any]:
    """Parse a composite URL id into a dict keyed by ``fields``.

    ``fields`` is an ordered list of ``(name, caster)`` — e.g.
    ``[("year", int), ("delivery_week", int), ("share_article", str),
    ("unit", str), ("size", str)]``. The id is split with ``maxsplit`` so a
    trailing field can't swallow earlier parts. Raises ``CompositeIdInvalid``
    (400, with the given ``code``) on a wrong part count or a cast failure —
    replacing the per-handler ``.split("_")`` unpacks that otherwise 500 on a
    malformed id or build divergent error shapes.
    """
    parts = raw.split("_", len(fields) - 1) if raw else []
    if len(parts) != len(fields):
        expected = "_".join(name for name, _ in fields)
        raise CompositeIdInvalid(
            f"Invalid id {raw!r}: expected {len(fields)} parts ({expected}).",
            code=code,
        )
    result: dict[str, Any] = {}
    for (name, caster), part in zip(fields, parts, strict=True):
        try:
            result[name] = caster(part)
        except (ValueError, TypeError) as exc:
            raise CompositeIdInvalid(
                f"Invalid {name} in id {raw!r}.", code=code
            ) from exc
    return result


def parse_composite_id(
    composite_id: str, *, code: str = "stock.invalid_composite_id"
) -> dict[str, Any]:
    """Parse the 7-part CurrentStock composite id into a dict.

    Format: ``share_article_id_unit_size_storage_id_year_week_day``. Raises
    ``CompositeIdInvalid`` (400) on a wrong part count or a bad year/week/day
    cast — replacing the old bare ``ValueError`` that callers had to wrap.

    (The 5-part planning ids use :func:`parse_composite_pk`; this variant stays
    separate because it decodes the CurrentStock ``"None"`` sentinel for the
    optional article/unit/size/storage parts.)

    Example:
        >>> parse_composite_id("abc123_kg_M_store1_2024_10_3")
        {"share_article_id": "abc123", "unit": "kg", "size": "M",
         "storage_id": "store1", "year": 2024, "delivery_week": 10,
         "day_number": 3}
    """
    parts = composite_id.split("_") if composite_id else []
    if len(parts) != 7:
        raise CompositeIdInvalid(
            f"Invalid composite id {composite_id!r}: expected 7 parts "
            "(share_article_unit_size_storage_year_week_day).",
            code=code,
        )
    try:
        year, week, day = int(parts[4]), int(parts[5]), int(parts[6])
    except (ValueError, TypeError) as exc:
        raise CompositeIdInvalid(
            f"Invalid year/week/day in id {composite_id!r}.", code=code
        ) from exc

    return {
        "share_article_id": parts[0] if parts[0] != "None" else None,
        "unit": parts[1] if parts[1] != "None" else None,
        "size": parts[2] if parts[2] != "None" else None,
        "storage_id": parts[3] if parts[3] != "None" else None,
        "year": year,
        "delivery_week": week,
        "day_number": day,
    }


def get_objects_by_regular_ids(
    model: type[Model], ids: list[str], filters: dict[str, Any] | None = None
) -> QuerySet:
    """
    Get objects by regular IDs.

    Args:
        model: Model class
        ids: List of regular ID strings
        filters: Additional filters (e.g., {"is_finalized": True})

    Returns:
        QuerySet of model instances
    """
    queryset = model.objects.filter(id__in=ids)

    if filters:
        queryset = queryset.filter(**filters)

    return queryset


def get_finalizable_objects(
    model_name: str,
    app_label: str,
    ids: list[str],
    filters: dict[str, Any] | None = None,
) -> tuple[type[Model], list[Model]]:
    """
    Get objects that support finalization.

    Args:
        model_name: Name of the model
        app_label: App label
        ids: List of IDs (regular or composite)
        filters: Additional filters

    Returns:
        Tuple of (Model class, list of objects)

    Raises:
        LookupError: If model not found
        ValueError: If model doesn't support finalization
    """
    model_class = apps.get_model(app_label, model_name)

    if not issubclass(model_class, FinalizableMixin):
        raise ValueError(f"{model_name} does not support finalization")

    objects = list(get_objects_by_regular_ids(model_class, ids, filters))

    return model_class, objects


def build_composite_id(
    share_article_id: str,
    unit: str | None,
    size: str | None,
    storage_id: str | None,
    year: int,
    delivery_week: int,
    day_number: int,
) -> str:
    """Build composite ID string from components."""
    parts = [
        str(share_article_id),
        str(unit) if unit is not None else "None",
        str(size) if size is not None else "None",
        str(storage_id) if storage_id is not None else "None",
        str(year),
        str(delivery_week),
        str(day_number),
    ]
    return "_".join(parts)
