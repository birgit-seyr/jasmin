from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .base import JasminModel


class SolverSettings(JasminModel):
    """The tenant's tunable placement-optimizer weights and feature flags.

    A partial-unique singleton (see ``Meta.constraints``) — the same idiom as
    ``commissioning.OfferGroup.is_default``. It lives in the tenant schema, so
    django-tenants scopes every read: no ``tenant`` FK, and a Huey worker under
    ``schema_context`` reads the right row without extra care.

    Mirrors ``optimizer.config.SolverConfig``; the module constants there stay
    the defaults, this row is the tenant's override. ``CELLS_PER_BED`` is
    deliberately NOT here — it is the solver's grain (snapshotted onto each
    plan), not a preference.
    """

    # Exactly one active row. Extra rows with is_active=False are the upgrade
    # path to named profiles (add a ``name`` column, keep this constraint).
    is_active = models.BooleanField(default=True)

    # --- Solver runtime ---
    solver_max_time_seconds = models.PositiveSmallIntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(7200)],
        help_text=(
            "Wall-clock budget for ONE solve. A hard plan legitimately needs "
            "10+ minutes, so this goes up to 2 hours; the default stays low for "
            "quick feedback. A run computes several plans, so the total is this "
            "times the number of solutions."
        ),
    )
    solver_workers = models.PositiveSmallIntegerField(
        default=8,
        validators=[MinValueValidator(1), MaxValueValidator(32)],
        help_text="CP-SAT search worker threads (num_search_workers).",
    )
    default_num_solutions = models.PositiveSmallIntegerField(
        default=4,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        help_text="How many distinct candidate plans one run produces.",
    )

    # --- Feature flags ---
    enable_planting_line_homogeneity = models.BooleanField(
        default=True,
        help_text=(
            "Within one bed, crops growing at the same time must share a "
            "planting line (hard constraint)."
        ),
    )
    enable_fleece = models.BooleanField(
        default=False,
        help_text=(
            "Cover fleece-needing crops with 4-bed-wide fleece units (hard) and "
            "minimise fleece-weeks (soft). Expensive: adds per-(plot, week, bed) "
            "variables."
        ),
    )
    enable_line_dispersion = models.BooleanField(
        default=False,
        help_text=(
            "Keep beds sharing a planting line near each other (soft, "
            "aesthetic). The priciest soft term."
        ),
    )

    # --- Objective weights (higher = more important) ---
    weight_plots_used = models.PositiveSmallIntegerField(
        default=100,
        validators=[MaxValueValidator(1000)],
        help_text="Consolidate the plan onto as few plots as possible.",
    )
    weight_beds_used = models.PositiveSmallIntegerField(
        default=10,
        validators=[MaxValueValidator(1000)],
        help_text="Fewer distinct beds across the season (rewards succession).",
    )
    weight_beds_per_batch = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(1000)],
        help_text=(
            "Keep each batch bed-aligned (spanning fewest beds). Defaults to 0: "
            "a crop may run from one bed into the next, and forcing bed-aligned "
            "starts strands the leftover cells of every bed, which wastes land."
        ),
    )
    weight_compact_span = models.PositiveSmallIntegerField(
        default=3,
        validators=[MaxValueValidator(1000)],
        help_text="No gaps between the first and last used bed of a plot.",
    )
    weight_line_dispersion = models.PositiveSmallIntegerField(
        default=1,
        validators=[MaxValueValidator(1000)],
        help_text="Group beds that share a planting line.",
    )
    weight_fleece_count = models.PositiveSmallIntegerField(
        default=10,
        validators=[MaxValueValidator(1000)],
        help_text="Minimise how many fleece-weeks the plan needs.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="solversettings_single_active",
            ),
        ]

    def __str__(self) -> str:
        return f"Solver settings ({self.updated_at:%Y-%m-%d})"

    @classmethod
    def get_active(cls) -> SolverSettings:
        """The tenant's active settings row, created on first read with the code
        defaults (an all-defaults row IS the previous hardcoded behaviour)."""
        settings, _ = cls.objects.get_or_create(is_active=True)
        return settings
