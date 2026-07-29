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


class SolutionNotFound(NotFoundError):
    code = "cultivation.solution_not_found"


class PlacementOutOfBounds(BadRequestError):
    """A manual placement would run past the end of the plot."""

    code = "cultivation.placement_out_of_bounds"


class PlacementOverlaps(ConflictError):
    """A manual placement collides with another batch in space and time."""

    code = "cultivation.placement_overlaps"
