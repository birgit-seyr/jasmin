from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsOffice, IsStaff, RolePermissionsMixin

from ..models.members import MemberLoan
from ..schemas import get_member_parameter, get_year_parameter
from ..serializers import MemberLoanSerializer
from ..utils.query_params import validate_query_params


# Stock DRF CRUD: ``retrieve`` / ``create`` / ``update`` / ``partial_update``
# all return a single ``MemberLoanSerializer`` (the viewset ``serializer_class``);
# ``destroy`` returns 204 No Content. Declared explicitly so spectacular doesn't
# infer them. (``list`` carries its own ``@extend_schema`` for its query params.)
@extend_schema_view(
    retrieve=extend_schema(responses={200: MemberLoanSerializer}),
    create=extend_schema(responses={201: MemberLoanSerializer}),
    update=extend_schema(responses={200: MemberLoanSerializer}),
    partial_update=extend_schema(responses={200: MemberLoanSerializer}),
    destroy=extend_schema(responses={204: None}),
)
class MemberLoanViewSet(RolePermissionsMixin, viewsets.ModelViewSet):
    """Office-managed register of member loans (interest-bearing loans
    the co-op accepts from its members).

    Filters mirror the existing ``CoopShareViewSet`` so the office UI
    can use the same year-+-member filter widgets on both pages —
    ``year`` filters by ``start_date__year``, ``member`` by the FK.
    Both are optional at runtime; the schema marks them as such so
    drf-spectacular doesn't reject calls that omit either.
    """

    read_permission = IsStaff
    write_permission = IsOffice
    serializer_class = MemberLoanSerializer

    @extend_schema(
        parameters=[
            get_member_parameter(required=False),
            get_year_parameter(required=False),
        ],
        responses={200: MemberLoanSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: MemberLoanSerializer) -> None:
        # Stamp authorship server-side (the field is read-only to clients).
        serializer.save(created_by=self.request.user)

    def get_queryset(self) -> QuerySet[MemberLoan]:
        queryset = MemberLoan.objects.all().select_related("member")

        # List-only, as on the sibling coop-share list: the detail route
        # addresses one loan by id and reads neither filter.
        if self.action == "list":
            params = validate_query_params(self.request, optional=["member", "year"])
            if params["member"]:
                queryset = queryset.filter(member=params["member"])
            if params["year"]:
                queryset = queryset.filter(start_date__year=params["year"])

        return queryset.order_by("-start_date")
