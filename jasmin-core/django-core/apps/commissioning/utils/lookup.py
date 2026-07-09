"""Shared object-lookup helper for viewsets/views.

``get_or_404`` is the single "fetch a row by id or raise a canonical domain
error" primitive. It replaces the hand-rolled ``try``/``DoesNotExist`` → raise
blocks (and the DRF ``get_object_or_404`` calls that produced a non-canonical
``{"detail": ...}`` body) scattered across the commissioning viewsets/views.

The raised exceptions are ``core.errors.JasminError`` subclasses, so the DRF
exception handler renders them as the structured Jasmin error body — callers
must NOT wrap this in ``try``/``except``.
"""

from __future__ import annotations

from typing import Any, TypeVar

from django.db.models import Model, QuerySet

from core.errors import BadRequestError, JasminError, NotFoundError

M = TypeVar("M", bound=Model)


def get_or_404(
    model: type[M],
    obj_id: Any,
    label: str,
    *,
    error_cls: type[JasminError] = NotFoundError,
    code: str | None = None,
    queryset: QuerySet[M] | None = None,
) -> M:
    """Return ``model.objects.get(id=obj_id)`` or raise a canonical domain error.

    Raises ``BadRequestError`` (code ``<label>.id_required``, ``field=<label>``)
    when ``obj_id`` is falsy, and ``error_cls`` when the row does not exist.

    ``error_cls`` defaults to the generic ``NotFoundError`` (code
    ``<label>.not_found``); pass a dedicated ``errors.py`` subclass — e.g.
    ``OrderNotFound`` — to emit its stable per-resource ``code`` instead. Pass
    ``code`` to override the emitted code explicitly, or ``queryset`` to fetch
    through a pre-built queryset (e.g. one carrying ``select_related``) while
    still keying on ``id``.

    ``<label>`` is snake-cased for the codes (``"Delivery note"`` →
    ``delivery_note``).
    """
    slug = label.lower().replace(" ", "_")
    if not obj_id:
        raise BadRequestError(
            f"{label} id is required",
            code=f"{slug}.id_required",
            field=slug,
        )
    source = queryset if queryset is not None else model.objects
    try:
        return source.get(id=obj_id)
    except model.DoesNotExist as exc:
        if error_cls is NotFoundError:
            raise NotFoundError(
                f"{label} not found",
                code=code or f"{slug}.not_found",
                details={"id": str(obj_id)},
            ) from exc
        # A dedicated subclass carries its own stable ``code`` (used when
        # ``code`` is None); keep the ``id`` detail for parity with the
        # generic branch.
        raise error_cls(
            f"{label} not found",
            code=code,
            details={"id": str(obj_id)},
        ) from exc
