"""Domain errors for the cultivation app.

Every error is a ``core.errors.JasminError`` subclass with a stable ``code`` the
frontend can branch on — raise these instead of bare DRF ``ValidationError`` or
hand-built ``Response`` objects. Callers pass the human message:
``raise NoBatchesToPlace("No finalized batches for 2027.")``.
"""

from core.errors import BadRequestError, ConflictError, NotFoundError


class NoBatchesToPlace(BadRequestError):
    """The year has no finalized batches, so there is nothing to solve."""

    code = "cultivation.no_batches_to_place"


class NoPlotsAvailable(BadRequestError):
    """No outdoor plot has any beds configured."""

    code = "cultivation.no_plots_available"


class BatchDoesNotFit(BadRequestError):
    """A batch needs more contiguous cells than any single plot offers."""

    code = "cultivation.batch_does_not_fit"


class BedTypeMismatch(BadRequestError):
    """A placement would put a batch on beds of the wrong type.

    ``amount_of_beds`` counts beds of the batch's ``used_bed_type``, so the same
    number of beds is a different area on a different type. A batch must sit
    wholly inside one block of its own bed type — spilling into the neighbouring
    block is the same mistake in slow motion.
    """

    code = "cultivation.bed_type_mismatch"


class SolutionNotFound(NotFoundError):
    code = "cultivation.solution_not_found"


class PlanInfeasible(BadRequestError):
    """The constraints contradict each other — no placement can satisfy them all.

    Distinct from a timeout: the solver *proved* there is no plan. Usual causes are
    more demand than land, a batch needing more contiguous cells than any plot has,
    or rotation history that leaves a family nowhere to go.
    """

    code = "cultivation.plan_infeasible"


class PlanSolveTimedOut(BadRequestError):
    """The solver ran out of its time budget before finding any plan.

    Unlike :class:`PlanInfeasible` a plan may well exist — raise the time budget or
    reduce the model (e.g. turn off planting-line homogeneity) and retry.
    """

    code = "cultivation.plan_solve_timed_out"


class PlacementOutOfBounds(BadRequestError):
    """A manual placement would run past the end of the plot."""

    code = "cultivation.placement_out_of_bounds"


class BatchPlacedTwice(BadRequestError):
    """One batch was given two positions in the same plan.

    A crop occupies one spot for its whole window — it cannot be in two places
    at once. Two placements for one batch would also slip past the collision
    check whenever their cells differ, so it is rejected explicitly.
    """

    code = "cultivation.batch_placed_twice"


class PlacementOverlaps(ConflictError):
    """A manual placement collides with another batch in space and time."""

    code = "cultivation.placement_overlaps"
