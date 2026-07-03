from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import APIViewRolePermissionsMixin, IsOffice, IsStaff
from core.errors import JasminError, NotFoundError
from core.serializers import ErrorResponseSerializer

from ..errors import CommissioningError, CompositeIdInvalid, FinalizedError
from ..models import DeliveryNoteReseller, InvoiceReseller, Order, ShareContent
from ..serializers import (
    BulkFinalizeRequestSerializer,
    BulkFinalizeResponseSerializer,
    BulkFinalizeShareContentRequestSerializer,
    BulkFinalizeShareContentResponseSerializer,
    BulkUnfinalizeResponseSerializer,
)
from ..services.bulk_operations import bulk_with_savepoints
from ..utils import get_finalizable_objects
from ..utils.composite_id_utils import parse_composite_pk

_SENTINEL = object()


def _validate_bulk_payload(*, ids: Any, model_name: Any = _SENTINEL) -> None:
    """Common payload validation for bulk-finalize endpoints.

    Omit ``model_name`` for endpoints that don't accept it (the ShareContent
    variants use composite IDs and don't need a model param).
    """
    if model_name is not _SENTINEL and not model_name:
        raise CommissioningError(
            "model parameter is required",
            field="model",
            code="finalize.model_required",
        )
    if not ids:
        raise CommissioningError(
            "ids parameter is required",
            field="ids",
            code="finalize.ids_required",
        )
    if not isinstance(ids, list):
        raise CommissioningError(
            "ids must be a list",
            field="ids",
            code="finalize.ids_not_list",
        )


class BulkFinalizeView(APIViewRolePermissionsMixin, APIView):
    """Bulk finalize objects that use FinalizableMixin."""

    read_permission = IsStaff
    write_permission = IsStaff

    @extend_schema(
        summary="Bulk Finalize Objects",
        description="""
        Finalize multiple objects at once.
        
        Supports:
        - Regular models with standard IDs (Order, DeliveryNote, etc.)
        - CurrentStock with composite IDs (format: share_article_id_unit_size_storage_id_year_week_day)
        
        Returns counts of:
        - Successfully finalized objects
        - Already finalized objects
        - Errors encountered
        """,
        request=BulkFinalizeRequestSerializer,
        responses={
            200: BulkFinalizeResponseSerializer,
            207: BulkFinalizeResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        """
        Finalize multiple objects.

        Args:
            request: HTTP request with model, app_label, and ids

        Returns:
            Response with finalization results
        """
        model_name = request.data.get("model")
        app_label = request.data.get("app_label", "commissioning")
        ids = request.data.get("ids", [])

        _validate_bulk_payload(model_name=model_name, ids=ids)

        try:
            _, objects = get_finalizable_objects(model_name, app_label, ids)
        except LookupError as exc:
            raise CommissioningError(
                f"Model {model_name} not found in app {app_label}",
                code="finalize.model_not_found",
            ) from exc

        if not objects:
            raise NotFoundError("No objects found with provided IDs")

        results = self._finalize_objects(objects, request.user)
        # 207 Multi-Status when any item failed, so clients branching on the
        # status line see the partial-success state instead of reading 200 and
        # skipping the errors[] array. Mirrors reseller_views _build_bulk_response.
        status_code = (
            status.HTTP_207_MULTI_STATUS if results["errors"] else status.HTTP_200_OK
        )
        return Response(
            {
                "message": "Finalization completed",
                "finalized_count": results["finalized_count"],
                "already_finalized_count": results["already_finalized_count"],
                "total_requested": len(ids),
                "errors": results["errors"],
            },
            status=status_code,
        )

    def _finalize_objects(self, objects: list, user: Any) -> dict[str, Any]:
        """
        Finalize a list of objects.

        Args:
            objects: List of objects to finalize
            user: User performing the action

        Returns:
            Dict with finalization results
        """
        finalized_count = 0
        already_finalized_count = 0
        errors: list[dict[str, str]] = []

        user = user if user.is_authenticated else None

        def finalize_one(obj: Any) -> None:
            nonlocal finalized_count, already_finalized_count
            if isinstance(
                obj, (InvoiceReseller, Order, DeliveryNoteReseller)
            ) and getattr(obj, "is_finalized", False):
                already_finalized_count += 1
                return
            if isinstance(obj, InvoiceReseller):
                from ..services import InvoiceService

                InvoiceService.finalize_invoice(obj, user=user)
                finalized_count += 1
            elif isinstance(obj, Order):
                from ..services import OrderService

                OrderService.finalize_order(obj, user=user)
                finalized_count += 1
            elif isinstance(obj, DeliveryNoteReseller):
                from ..services import DeliveryNoteService

                DeliveryNoteService.finalize_delivery_note(obj, user=user)
                finalized_count += 1
            elif obj.finalize(user=user):
                finalized_count += 1
            else:
                already_finalized_count += 1

        def record_error(obj: Any, exc: Exception) -> None:
            obj_id = getattr(obj, "id", "unknown")
            errors.append({"id": str(obj_id), "error": str(exc)})

        # ``JasminError`` is in the catch set because the commissioning
        # finalizers raise domain errors for a bad item (e.g. an empty
        # invoice/delivery note → 400-class ``CommissioningError``); those
        # must be collected per item, not escape and abort the whole batch.
        bulk_with_savepoints(
            objects,
            finalize_one,
            catch=(
                DatabaseError,
                DjangoValidationError,
                ValueError,
                TypeError,
                AttributeError,
                JasminError,
            ),
            on_error=record_error,
        )

        return {
            "finalized_count": finalized_count,
            "already_finalized_count": already_finalized_count,
            "errors": errors,
        }


class BulkUnfinalizeView(APIViewRolePermissionsMixin, APIView):
    """Bulk unfinalize objects that use FinalizableMixin."""

    read_permission = IsStaff
    write_permission = IsStaff

    @extend_schema(
        summary="Bulk Unfinalize Objects",
        description="""
        Unfinalize multiple objects at once.
        
        Supports:
        - Regular models with standard IDs (Order, DeliveryNote, etc.)
        - CurrentStock with composite IDs (format: share_article_id_unit_size_storage_id_year_week_day)
        
        Only processes objects that are currently finalized.
        """,
        request=BulkFinalizeRequestSerializer,
        responses={
            200: BulkUnfinalizeResponseSerializer,
            409: ErrorResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        """
        Unfinalize multiple objects.

        Args:
            request: HTTP request with model, app_label, and ids

        Returns:
            Response with unfinalization results
        """
        model_name = request.data.get("model")
        app_label = request.data.get("app_label", "commissioning")
        ids = request.data.get("ids", [])

        _validate_bulk_payload(model_name=model_name, ids=ids)

        try:
            model, objects = get_finalizable_objects(
                model_name, app_label, ids, filters={"is_finalized": True}
            )
        except LookupError as exc:
            raise CommissioningError(
                f"Model {model_name} not found in app {app_label}",
                code="finalize.model_not_found",
            ) from exc

        if not objects:
            raise NotFoundError("No finalized objects found with provided IDs")

        # Reject one-way models up front instead of letting the first
        # ``obj.unfinalize()`` raise mid-loop: Order, DeliveryNoteReseller
        # and InvoiceReseller override ``unfinalize()`` to unconditionally
        # raise, so the declared 200 would be unreachable for them. The
        # empty-check stays first — "no finalized rows matched" is a 404
        # regardless of model (see test_404_if_none_are_finalized).
        if getattr(model, "IS_FINALIZED_ONE_WAY", False):
            raise FinalizedError(
                f"{model_name} documents are legally immutable once "
                "finalized and cannot be unfinalized. To reverse, create "
                "a storno; to revise, issue a correction document.",
                code="finalize.one_way_model",
            )

        for obj in objects:
            obj.unfinalize()

        return Response(
            {
                "message": f"Successfully unfinalized {len(objects)} objects",
                "unfinalized_count": len(objects),
            },
            status=status.HTTP_200_OK,
        )


_SHARE_CONTENT_PK_FIELDS = [
    ("share__year", int),
    ("share__delivery_week", int),
    ("share_article_id", str),
    ("unit", str),
    ("size", str),
]


def _parse_share_content_composite_id(composite_id: str) -> dict[str, Any]:
    """Parse a share content composite id (year_week_shareArticleId_unit_size)
    into ORM filter kwargs. Raises ``CompositeIdInvalid`` (400) on a malformed
    id; the bulk callers catch it to collect a per-item error."""
    return parse_composite_pk(
        composite_id,
        fields=_SHARE_CONTENT_PK_FIELDS,
        code="share_content.invalid_composite_id",
    )


def _get_share_contents_for_composite_ids(
    composite_ids: list[str],
) -> tuple[list[ShareContent], list[dict[str, str]]]:
    """Resolve composite IDs to ShareContent objects.

    Returns:
        Tuple of (list of ShareContent objects, list of errors)
    """
    from django.db.models import Q

    q_filter = Q()
    errors: list[dict[str, str]] = []

    for composite_id in composite_ids:
        try:
            params = _parse_share_content_composite_id(composite_id)
            q_filter |= Q(**params)
        except CompositeIdInvalid as e:
            errors.append({"id": composite_id, "error": str(e)})

    if not q_filter:
        return [], errors

    objects = list(ShareContent.objects.filter(q_filter))
    return objects, errors


def _get_finalization_status(composite_ids: list[str]) -> dict[str, bool]:
    """Check finalization status for each composite ID.

    Returns a dict of composite_id → bool where True means the group has at
    least one row AND every ShareContent row in it is finalized.

    Runs a SINGLE grouped aggregation rather than two count() queries per ID:
    the previous per-ID loop was an N+1 (1–2 queries × N composite IDs).
    """
    from django.db.models import Count, Q

    group_fields = [field for field, _caster in _SHARE_CONTENT_PK_FIELDS]

    # Every requested ID defaults to False; a malformed ID stays False, and a
    # well-formed ID whose group has zero rows never appears in the aggregation
    # below (so it also stays False — the empty-group case, made explicit by the
    # ``total > 0`` guard rather than relying on an early return).
    result: dict[str, bool] = {}
    q_filter = Q()
    # Parse each ID to its group-by key. Keyed per INPUT id (a list per key) so
    # two distinct id strings that parse to the SAME key (e.g. "2026_07_…" vs
    # "2026_7_…") both receive the group's verdict instead of one silently
    # shadowing the other.
    ids_by_key: dict[tuple, list[str]] = {}
    for composite_id in composite_ids:
        try:
            params = _parse_share_content_composite_id(composite_id)
        except CompositeIdInvalid:
            result[composite_id] = False
            continue
        result.setdefault(composite_id, False)
        q_filter |= Q(**params)
        ids_by_key.setdefault(
            tuple(params[field] for field in group_fields), []
        ).append(composite_id)

    if not ids_by_key:
        return result

    rows = (
        ShareContent.objects.filter(q_filter)
        .values(*group_fields)
        .annotate(
            total=Count("id"),
            finalized=Count("id", filter=Q(is_finalized=True)),
        )
    )
    for row in rows:
        key = tuple(row[field] for field in group_fields)
        is_finalized = row["total"] > 0 and row["finalized"] == row["total"]
        for composite_id in ids_by_key.get(key, ()):
            result[composite_id] = is_finalized

    return result


class BulkFinalizeShareContentView(APIViewRolePermissionsMixin, APIView):
    """Bulk finalize ShareContent objects using planning composite IDs."""

    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Finalize Share Content",
        description="""
        Finalize all ShareContent objects matching the given composite IDs.
        
        Each composite ID has the format: year_week_shareArticleId_unit_size
        (e.g., 2026_14_SCKgsTKB9pSP_PCS_M).
        
        This resolves to ALL ShareContent rows with matching
        share__year, share__delivery_week, share_article, unit, and size.
        
        Returns finalization counts and a per-ID finalization status map.
        """,
        request=BulkFinalizeShareContentRequestSerializer,
        responses={
            200: BulkFinalizeShareContentResponseSerializer,
            207: BulkFinalizeShareContentResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        ids = request.data.get("ids", [])
        _validate_bulk_payload(ids=ids)

        objects, errors = _get_share_contents_for_composite_ids(ids)

        if not objects and not errors:
            raise NotFoundError("No ShareContent objects found for provided IDs")

        finalized_count = 0
        already_finalized_count = 0
        user = request.user if request.user.is_authenticated else None

        def count_result(obj: ShareContent, finalized: bool) -> None:
            nonlocal finalized_count, already_finalized_count
            if finalized:
                finalized_count += 1
            else:
                already_finalized_count += 1

        def record_error(obj: ShareContent, exc: Exception) -> None:
            errors.append({"id": str(obj.id), "error": str(exc)})

        bulk_with_savepoints(
            objects,
            lambda obj: obj.finalize(user=user),
            catch=(
                DatabaseError,
                DjangoValidationError,
                ValueError,
                TypeError,
                AttributeError,
            ),
            on_error=record_error,
            on_success=count_result,
        )

        status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response(
            {
                "message": "Finalization completed",
                "finalized_count": finalized_count,
                "already_finalized_count": already_finalized_count,
                "total_requested": len(ids),
                "errors": errors,
                "finalization_status": _get_finalization_status(ids),
            },
            status=status_code,
        )


class BulkUnfinalizeShareContentView(APIViewRolePermissionsMixin, APIView):
    """Bulk unfinalize ShareContent objects using planning composite IDs."""

    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Unfinalize Share Content",
        description="""
        Unfinalize all ShareContent objects matching the given composite IDs.
        
        Each composite ID has the format: year_week_shareArticleId_unit_size.
        Only processes objects that are currently finalized.
        
        Returns unfinalization count and a per-ID finalization status map.
        """,
        request=BulkFinalizeShareContentRequestSerializer,
        responses={
            200: BulkFinalizeShareContentResponseSerializer,
            207: BulkFinalizeShareContentResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        ids = request.data.get("ids", [])
        _validate_bulk_payload(ids=ids)

        objects, errors = _get_share_contents_for_composite_ids(ids)

        if not objects and not errors:
            raise NotFoundError("No ShareContent objects found for provided IDs")

        unfinalized_count = 0
        already_unfinalized_count = 0

        def unfinalize_one(obj: ShareContent) -> bool:
            was_finalized = obj.is_finalized
            if was_finalized:
                obj.unfinalize()
            return was_finalized

        def count_result(obj: ShareContent, was_finalized: bool) -> None:
            nonlocal unfinalized_count, already_unfinalized_count
            if was_finalized:
                unfinalized_count += 1
            else:
                already_unfinalized_count += 1

        def record_error(obj: ShareContent, exc: Exception) -> None:
            errors.append({"id": str(obj.id), "error": str(exc)})

        bulk_with_savepoints(
            objects,
            unfinalize_one,
            catch=(
                DatabaseError,
                DjangoValidationError,
                ValueError,
                TypeError,
                AttributeError,
            ),
            on_error=record_error,
            on_success=count_result,
        )

        status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response(
            {
                "message": f"Successfully unfinalized {unfinalized_count} objects",
                "finalized_count": 0,
                "already_finalized_count": already_unfinalized_count,
                "total_requested": len(ids),
                "errors": errors,
                "finalization_status": _get_finalization_status(ids),
            },
            status=status_code,
        )
