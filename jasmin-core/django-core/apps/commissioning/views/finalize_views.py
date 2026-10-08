from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authz.permissions import (
    APIViewRolePermissionsMixin,
    IsOffice,
    IsStaff,
    has_any_role,
)
from apps.shared.request_utils import auth_user, body
from core.errors import ForbiddenError, JasminError, NotFoundError
from core.serializers import ErrorResponseSerializer

from ..errors import (
    BulkFinalizeAppLabelInvalid,
    BulkFinalizeIdsInvalid,
    BulkFinalizeModelInvalid,
    CommissioningError,
    CompositeIdInvalid,
    FinalizedError,
)
from ..models import (
    DeliveryNoteReseller,
    Forecast,
    Harvest,
    InvoiceReseller,
    Order,
    ShareContent,
)
from ..serializers import (
    BulkFinalizeRequestSerializer,
    BulkFinalizeResponseSerializer,
    BulkFinalizeShareContentResponseSerializer,
    BulkIdsRequestSerializer,
    BulkUnfinalizeResponseSerializer,
)
from ..services.bulk_operations import bulk_with_savepoints
from ..services.finalization_quota import (
    FinalizationReservation,
    reserve_finalizations,
)
from ..services.planning_slots import PlanningSlot
from ..utils import get_finalizable_objects
from ..utils.read_only_week import refuse_read_only_week
from ..utils.validation_utils import parse_bulk_ids


def _require_model_name(model_name: Any) -> None:
    """Reject a bulk-finalize request whose ``model`` param is missing.

    The ShareContent variants use composite IDs and don't accept a model, so
    only the model-keyed finalize/unfinalize endpoints call this.
    """
    if not model_name:
        raise CommissioningError(
            "model parameter is required",
            field="model",
            code="finalize.model_required",
        )


# Models any staff role may (un)finalize through the generic bulk endpoints:
# the records behind the staff-gated Forecast and Harvest pages, and offers
# (published to resellers, reversible). Every other finalizable model — the
# legally one-way orders, delivery notes and invoices with their line models,
# and ShareContent — needs office, the same gate as the dedicated
# BulkFinalizeDocumentsView and the share-content (un)finalize endpoints. An
# allowlist, so a newly finalizable model starts out office-only.
_STAFF_FINALIZABLE_MODELS = frozenset({"forecast", "harvest", "offer"})


def _validate_bulk_finalize_request(request: Request) -> tuple[list[str], str]:
    """Validate a generic bulk (un)finalize body and gate its model by role.

    Returns ``(ids, model_name)`` with ``model_name`` normalised to the
    lowercase model name. Raises a 400 for a malformed body and a 403 when a
    non-office staff role names an office-only model. The role check runs
    before any row is looked up, so a refused caller learns nothing about
    which ids exist.
    """
    # Run the long-standing checks first so a missing / empty ids list and a
    # missing model keep their existing error codes.
    parse_bulk_ids(request, invalid_item_error=BulkFinalizeIdsInvalid)
    _require_model_name(body(request).get("model"))

    serializer = BulkFinalizeRequestSerializer(data=body(request))
    if not serializer.is_valid():
        # The body is a dict (parse_bulk_ids passed), so every error is keyed
        # by one of the three declared fields.
        errors = serializer.errors
        if "ids" in errors:
            raise BulkFinalizeIdsInvalid("Every id must be a string.", field="ids")
        if "model" in errors:
            raise BulkFinalizeModelInvalid(
                "model must name a finalizable commissioning model.",
                field="model",
            )
        raise BulkFinalizeAppLabelInvalid(
            "app_label must be 'commissioning'.", field="app_label"
        )

    model_name: str = serializer.validated_data["model"]
    if model_name not in _STAFF_FINALIZABLE_MODELS and not has_any_role(
        request, *IsOffice.required_roles
    ):
        raise ForbiddenError(
            f"Only office may finalize or unfinalize {model_name} records.",
            field="model",
        )
    return list(serializer.validated_data["ids"]), model_name


def _refuse_read_only_documentation_week(obj: Any) -> None:
    """Refuse a forecast or harvest in a week its page shows read-only.

    Their other writes refuse the same weeks. The other finalizable models
    carry their own rules for closed weeks.
    """
    if isinstance(obj, (Forecast, Harvest)):
        refuse_read_only_week(obj.year, obj.delivery_week)


class BulkFinalizeView(APIViewRolePermissionsMixin, APIView):
    """Bulk finalize objects that use FinalizableMixin."""

    read_permission = IsStaff
    write_permission = IsStaff

    @extend_schema(
        summary="Bulk Finalize Objects",
        description="""
        Finalize multiple objects at once.
        
        Supports:
        - Finalizable commissioning models, by model name (case-insensitive)
        - offer, forecast and harvest need a staff role; every other model
          (orders, delivery notes, invoices, their lines, share contents)
          needs office
        
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
        ids, model_name = _validate_bulk_finalize_request(request)

        try:
            _, objects = get_finalizable_objects(model_name, "commissioning", ids)
        except (LookupError, ValueError) as exc:
            raise BulkFinalizeModelInvalid(
                f"{model_name} cannot be finalized.", field="model"
            ) from exc

        if not objects:
            raise NotFoundError("No objects found with provided IDs")

        results = self._finalize_objects(objects, auth_user(request))
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

        reservations = self._reserve(objects, user)

        def finalize_one(obj: Any) -> None:
            nonlocal finalized_count, already_finalized_count
            _refuse_read_only_documentation_week(obj)
            if (
                isinstance(obj, (InvoiceReseller, Order, DeliveryNoteReseller))
                and obj.is_finalized
            ):
                already_finalized_count += 1
                return
            if isinstance(obj, InvoiceReseller):
                from ..services import InvoiceService

                InvoiceService.finalize_invoice(obj, user=user, skip_quota=True)
                finalized_count += 1
            elif isinstance(obj, Order):
                from ..services import OrderService

                OrderService.finalize_order(obj, user=user)
                finalized_count += 1
            elif isinstance(obj, DeliveryNoteReseller):
                from ..services import DeliveryNoteService

                DeliveryNoteService.finalize_delivery_note(
                    obj, user=user, skip_quota=True
                )
                finalized_count += 1
            elif obj.finalize(user=user):
                finalized_count += 1
            else:
                already_finalized_count += 1

        def record_error(obj: Any, exc: Exception) -> None:
            error = {"id": str(obj.id), "error": str(exc)}
            if isinstance(exc, JasminError):
                # The stable code lets a client translate the refusal.
                error["code"] = exc.code
            errors.append(error)

        # ``JasminError`` is in the catch set because the commissioning
        # finalizers raise domain errors for a bad item (e.g. an empty
        # invoice/delivery note → 400-class ``CommissioningError``); those
        # must be collected per item, not escape and abort the whole batch.
        # ``AttributeError`` / ``TypeError`` are deliberately NOT caught — they
        # signal a programming bug, not a per-item data problem, and must
        # surface (a 500) rather than be silently recorded as an item "error".
        bulk_with_savepoints(
            objects,
            finalize_one,
            catch=(
                DatabaseError,
                DjangoValidationError,
                ValueError,
                JasminError,
            ),
            on_error=record_error,
        )
        for reservation in reservations:
            reservation.release_unused()

        return {
            "finalized_count": finalized_count,
            "already_finalized_count": already_finalized_count,
            "errors": errors,
        }

    @staticmethod
    def _reserve(objects: list, user: Any) -> list[FinalizationReservation]:
        """Reserve the invoice and delivery-note finalizations this batch may
        perform, up front, so an over-cap batch is refused (429) before any
        item is finalized; the items are then finalized with ``skip_quota``.
        Only documents not yet final count, and finalizing an invoice also
        finalizes the delivery notes behind it. Runs inside the view's
        ``@transaction.atomic``, so a refusal rolls back cleanly."""
        from apps.shared.tenants.models import RateLimitedAction

        from ..services import InvoiceService

        invoice_ids = {
            obj.pk
            for obj in objects
            if isinstance(obj, InvoiceReseller) and not obj.is_finalized
        }
        delivery_note_ids = {
            obj.pk
            for obj in objects
            if isinstance(obj, DeliveryNoteReseller) and not obj.is_finalized
        } | InvoiceService.unfinalized_upstream_delivery_note_ids(invoice_ids)
        return [
            reserve_finalizations(
                RateLimitedAction.INVOICE_FINALIZATION,
                InvoiceReseller.objects.filter(pk__in=invoice_ids),
                actor=user,
            ),
            reserve_finalizations(
                RateLimitedAction.DELIVERY_NOTE_FINALIZATION,
                DeliveryNoteReseller.objects.filter(pk__in=delivery_note_ids),
                actor=user,
            ),
        ]


class BulkUnfinalizeView(APIViewRolePermissionsMixin, APIView):
    """Bulk unfinalize objects that use FinalizableMixin."""

    read_permission = IsStaff
    write_permission = IsStaff

    @extend_schema(
        summary="Bulk Unfinalize Objects",
        description="""
        Unfinalize multiple objects at once.
        
        Supports:
        - Finalizable commissioning models, by model name (case-insensitive)
        - offer, forecast and harvest need a staff role; every other model
          (orders, delivery notes, invoices, their lines, share contents)
          needs office
        
        Only processes objects that are currently finalized.
        """,
        request=BulkFinalizeRequestSerializer,
        responses={
            200: BulkUnfinalizeResponseSerializer,
            # A one-way model, or a forecast or harvest in a read-only week
            # (``commissioning.past_week``).
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
        ids, model_name = _validate_bulk_finalize_request(request)

        try:
            model, objects = get_finalizable_objects(
                model_name, "commissioning", ids, filters={"is_finalized": True}
            )
        except (LookupError, ValueError) as exc:
            raise BulkFinalizeModelInvalid(
                f"{model_name} cannot be unfinalized.", field="model"
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
                f"{model.__name__} documents are legally immutable once "
                "finalized and cannot be unfinalized. To reverse, create "
                "a storno; to revise, issue a correction document.",
                code="finalize.one_way_model",
            )

        # All or nothing, like the one-way refusal above: nothing is
        # unfinalized while one of the rows lies in a read-only week.
        for obj in objects:
            _refuse_read_only_documentation_week(obj)
        for obj in objects:
            obj.unfinalize()

        return Response(
            {
                "message": f"Successfully unfinalized {len(objects)} objects",
                "unfinalized_count": len(objects),
            },
            status=status.HTTP_200_OK,
        )


def _parse_planning_slot(composite_id: str) -> PlanningSlot:
    """The planning slot a composite id names (see ``PlanningSlot``). Raises
    ``CompositeIdInvalid`` (400) on a malformed id; the bulk callers catch it
    to collect a per-item error."""
    return PlanningSlot.parse(composite_id, code="share_content.invalid_composite_id")


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
            q_filter |= _parse_planning_slot(composite_id).share_contents_q()
        except CompositeIdInvalid as e:
            errors.append({"id": composite_id, "error": str(e)})

    if not q_filter:
        return [], errors

    objects = list(ShareContent.objects.filter(q_filter))
    return objects, errors


# A slot's share contents grouped by its fields, in ``PlanningSlot.key`` order.
_SLOT_GROUP_FIELDS = (
    "share__year",
    "share__delivery_week",
    "share_article_id",
    "unit",
    "size",
    "share__share_type_variation__share_type__share_option",
)


def _get_finalization_status(composite_ids: list[str]) -> dict[str, bool]:
    """Check finalization status for each composite ID.

    Returns a dict of composite_id → bool where True means the slot has at
    least one row AND every ShareContent row in it is finalized; a malformed
    id is False.

    Runs a SINGLE grouped aggregation rather than two count() queries per ID
    (an N+1 over the composite IDs). Each id is looked up by its parsed slot,
    so two strings naming one slot ("2026_07_…" and "2026_7_…") both get its
    verdict.
    """
    from django.db.models import Count, Q

    result: dict[str, bool] = {}
    slot_by_id: dict[str, PlanningSlot] = {}
    for composite_id in composite_ids:
        try:
            slot_by_id[composite_id] = _parse_planning_slot(composite_id)
        except CompositeIdInvalid:
            result[composite_id] = False

    if not slot_by_id:
        return result

    q_filter = Q()
    for slot in slot_by_id.values():
        q_filter |= slot.share_contents_q()
    rows = (
        ShareContent.objects.filter(q_filter)
        .values(*_SLOT_GROUP_FIELDS)
        .annotate(
            total=Count("id"),
            finalized=Count("id", filter=Q(is_finalized=True)),
        )
    )
    # Counted per slot of one share option, and summed under a ``None`` option
    # for the slot of every option, which an id without the option names. A
    # set, as a share type without an option has its rows there already.
    counts: dict[tuple[Any, ...], tuple[int, int]] = {}
    for row in rows:
        slot_key = tuple(row[field] for field in _SLOT_GROUP_FIELDS)
        for key in {slot_key, (*slot_key[:-1], None)}:
            total, finalized = counts.get(key, (0, 0))
            counts[key] = (total + row["total"], finalized + row["finalized"])

    for composite_id, slot in slot_by_id.items():
        total, finalized = counts.get(slot.key, (0, 0))
        result[composite_id] = total > 0 and finalized == total
    return result


class BulkFinalizeShareContentView(APIViewRolePermissionsMixin, APIView):
    """Bulk finalize ShareContent objects using planning composite IDs."""

    read_permission = IsOffice
    write_permission = IsOffice

    @extend_schema(
        summary="Bulk Finalize Share Content",
        description="""
        Finalize all ShareContent objects matching the given composite IDs.

        Each composite ID has the format:
        year_week_shareArticleId_unit_size_shareOption
        (e.g., 2026_14_SCKgsTKB9pSP_PCS_M_HARVEST_SHARE).

        This resolves to ALL ShareContent rows with matching
        share__year, share__delivery_week, share_article, unit and size
        whose variation belongs to the share option; an id without the
        share option matches the slot in every option.

        Returns finalization counts and a per-ID finalization status map.
        """,
        request=BulkIdsRequestSerializer,
        responses={
            200: BulkFinalizeShareContentResponseSerializer,
            207: BulkFinalizeShareContentResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        ids = parse_bulk_ids(request)

        objects, errors = _get_share_contents_for_composite_ids(ids)

        if not objects and not errors:
            raise NotFoundError("No ShareContent objects found for provided IDs")

        finalized_count = 0
        already_finalized_count = 0
        user = auth_user(request)

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

        Each composite ID has the format:
        year_week_shareArticleId_unit_size_shareOption; an id without the
        share option matches the slot in every option.
        Only processes objects that are currently finalized.
        
        Returns unfinalization count and a per-ID finalization status map.
        """,
        request=BulkIdsRequestSerializer,
        responses={
            200: BulkFinalizeShareContentResponseSerializer,
            207: BulkFinalizeShareContentResponseSerializer,
        },
    )
    @transaction.atomic
    def post(self, request: Request) -> Response:
        ids = parse_bulk_ids(request)

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
