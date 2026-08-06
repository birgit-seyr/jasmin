from typing import Any

from django.db.models import Count
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.permissions import IsGardener, IsStaff, RolePermissionsMixin

from ..errors import NoBatchesToPlace, NoPlotsAvailable
from ..models import CultivationPlanSolution
from ..schemas import get_year_parameter
from ..serializers import (
    CultivationPlanSolutionSerializer,
    CultivationPlanSolutionWithDetailsSerializer,
)
from ..services.placements import ProposedPlacement, choose_solution, save_placements


class CultivationPlanSolutionViewSet(
    RolePermissionsMixin, viewsets.ReadOnlyModelViewSet
):
    """Candidate placement plans produced by the solver.

    Read-only for the plans themselves (they are generated, not authored), plus
    three actions: kick off a solver run, mark a candidate as *the* plan, and
    store a hand-adjusted set of placements.
    """

    read_permission = IsStaff
    write_permission = IsGardener
    serializer_class = CultivationPlanSolutionSerializer

    def get_queryset(self):
        # metrics reads every placement, so prefetch — otherwise listing N
        # candidates is N queries.
        qs = (
            CultivationPlanSolution.objects.annotate(placement_count=Count("details"))
            .prefetch_related("details__batch")
            .order_by("-year", "version")
        )
        year = self.request.query_params.get("year")
        if year:
            qs = qs.filter(year=year)
        return qs

    def get_serializer_class(self):
        # The detail view carries every placement so the planner grid renders
        # from a single request.
        if self.action == "retrieve":
            return CultivationPlanSolutionWithDetailsSerializer
        return CultivationPlanSolutionSerializer

    @extend_schema(parameters=[get_year_parameter(required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=inline_serializer(
            name="RunCultivationSolverRequest",
            fields={
                "year": drf_serializers.IntegerField(),
                "num_solutions": drf_serializers.IntegerField(
                    required=False,
                    help_text="Defaults to the tenant's solver setting.",
                ),
            },
        ),
        responses={
            202: inline_serializer(
                name="RunCultivationSolverResponse",
                fields={
                    "job_id": drf_serializers.UUIDField(),
                    "kind": drf_serializers.CharField(),
                    "status": drf_serializers.CharField(),
                },
            )
        },
    )
    @action(detail=False, methods=["post"], url_path="run")
    def run(self, request: Request) -> Response:
        """Enqueue a solver run for a year; poll the returned job for progress.

        Inputs are validated synchronously so an unplannable year is a 400 here
        rather than a job that fails minutes later.
        """
        from apps.notifications.jobs import enqueue_job

        from ..optimizer.loading import load_batches, load_plots
        from ..tasks import run_cultivation_solver

        year = request.data.get("year")
        if year in (None, ""):
            raise NoBatchesToPlace("A year is required.", field="year")
        year = int(year)
        num_solutions = request.data.get("num_solutions")

        if not load_batches(year):
            raise NoBatchesToPlace(
                f"No finalized batches with a bed demand exist for {year}.",
                field="year",
            )
        if not any(plot.cell_capacity > 0 for plot in load_plots()):
            raise NoPlotsAvailable(
                "No outdoor plot has beds configured — add plot contents first."
            )

        job = enqueue_job(
            kind="cultivation.solve_plan",
            task=run_cultivation_solver,
            task_kwargs={
                "year": year,
                "num_solutions": int(num_solutions) if num_solutions else None,
            },
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(
            {"job_id": job.id, "kind": job.kind, "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )

    # request=None: the action takes no body (the pk in the URL is the whole
    # input), otherwise the generated client demands a pointless payload.
    @extend_schema(request=None, responses={200: CultivationPlanSolutionSerializer})
    @action(detail=True, methods=["post"], url_path="choose")
    def choose(self, request: Request, pk: str | None = None) -> Response:
        """Mark this candidate as the year's chosen plan (unsets any other)."""
        solution = choose_solution(self.get_object())
        solution.placement_count = solution.details.count()
        return Response(CultivationPlanSolutionSerializer(solution).data)

    @extend_schema(
        request=inline_serializer(
            name="SavePlacementsRequest",
            fields={
                "placements": drf_serializers.ListField(
                    child=drf_serializers.DictField(
                        child=drf_serializers.CharField(),
                        help_text="{batch, plot, start_cell}",
                    )
                ),
            },
        ),
        responses={200: CultivationPlanSolutionWithDetailsSerializer},
    )
    @action(detail=True, methods=["post"], url_path="save_placements")
    def save_placements(self, request: Request, pk: str | None = None) -> Response:
        """Replace this plan's placements with a hand-adjusted set.

        Only physically impossible states are rejected (out of bounds, or two
        crops sharing a cell in the same week) — agronomic judgement stays with
        the gardener.
        """
        solution = self.get_object()
        raw = request.data.get("placements") or []
        proposed = [
            ProposedPlacement(
                batch_id=str(item["batch"]),
                plot_id=str(item["plot"]),
                start_cell=int(item["start_cell"]),
            )
            for item in raw
        ]
        save_placements(solution, proposed)
        solution = (
            CultivationPlanSolution.objects.annotate(placement_count=Count("details"))
            .prefetch_related("details__batch__vegetable")
            .get(pk=solution.pk)
        )
        return Response(CultivationPlanSolutionWithDetailsSerializer(solution).data)
