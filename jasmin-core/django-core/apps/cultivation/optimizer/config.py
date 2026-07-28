"""Tunable parameters for the placement optimizer.

Weights and feature flags for the full constraint set ported from the old
``optimizer_folder``. The heavier / more approximate features (fleece, planting-
line dispersion) are gated OFF by default but fully implemented — flip the flag
to bring them in. The real objective ("optimal of what") is still an open design
question, so the weights below are a sensible placeholder, not a final answer.
"""

from ..constants import CELLS_PER_BED

# Grain: how many optimizer cells make up one gardener's bed. Re-exported here
# so the rest of the package imports it from one place; snapshotted onto each
# CultivationPlanSolution so an old plan keeps its meaning if this ever changes.
__all__ = [
    "CELLS_PER_BED",
    "SOLVER_MAX_TIME_SECONDS",
    "SOLVER_WORKERS",
    "DEFAULT_NUM_SOLUTIONS",
    "WEEKS_PER_YEAR",
    "END_WEEK_IS_INCLUSIVE",
    "ENABLE_PLANTING_LINE_HOMOGENEITY",
    "ENABLE_FLEECE",
    "ENABLE_LINE_DISPERSION",
    "FLEECE_WIDTH_IN_BEDS",
    "WEIGHT_PLOTS_USED",
    "WEIGHT_BEDS_USED",
    "WEIGHT_BEDS_PER_BATCH",
    "WEIGHT_COMPACT_SPAN",
    "WEIGHT_LINE_DISPERSION",
    "WEIGHT_FLEECE_COUNT",
]

# Solver runtime.
SOLVER_MAX_TIME_SECONDS = 60.0
SOLVER_WORKERS = 8

# How many distinct candidate plans to produce per run.
DEFAULT_NUM_SOLUTIONS = 4

# Weeks in a planning year. Used to unwrap overwintering crops onto an absolute
# time axis: a batch with end_week < planting_week (planted in autumn, freed the
# next spring) runs into next year, so its end is shifted by this amount.
WEEKS_PER_YEAR = 52

# A batch occupies its cells for weeks [planting_week, end_week]. If end_week is
# the LAST occupied week (the spot is free again the week after), this is True
# and the time interval spans end_week - planting_week + 1 weeks. If end_week is
# instead the FIRST free week, set this False. See CultivationBatch.end_week
# ("after this: new stuff can be planted on the same spot").
END_WEEK_IS_INCLUSIVE = True

# --- Feature flags -----------------------------------------------------------
# Within one bed, all crops present at the same time must share a planting line
# (hard). Needs the per-bed occupancy bridge; moderate cost.
ENABLE_PLANTING_LINE_HOMOGENEITY = True

# Crops that need fleece must be covered by a fleece unit (a 4-bed-wide cover)
# in every week of their fleece window (hard), and the number of fleece-weeks is
# minimised (soft). Expensive: adds per-(plot, week, bed) fleece variables — off
# by default, flip on when you want it.
ENABLE_FLEECE = False
FLEECE_WIDTH_IN_BEDS = 4

# Encourage beds that share a planting line to sit near each other (soft, purely
# aesthetic). Pairwise bed-distance penalty — the priciest soft term; off by
# default.
ENABLE_LINE_DISPERSION = False

# --- Objective weights -------------------------------------------------------
# Higher = more important. Consolidating onto few plots dominates; the rest are
# packing-quality tie-breakers.
WEIGHT_PLOTS_USED = 100
WEIGHT_BEDS_USED = 10  # fewer distinct beds across the season (rewards succession)
WEIGHT_BEDS_PER_BATCH = 5  # keep each batch bed-aligned (fewest beds spanned)
WEIGHT_COMPACT_SPAN = 3  # no gaps between the first and last used bed of a plot
WEIGHT_LINE_DISPERSION = 1
WEIGHT_FLEECE_COUNT = 10
