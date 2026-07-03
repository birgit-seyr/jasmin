"""
Configuration settings for the cultivation plan optimizer.
This file centralizes all constants and field definitions used in optimization.
"""

# Time constants
WEEKS_PER_YEAR = 52
EXTRA_WEEKS_PER_YEAR = 10  # Buffer weeks, because of year overlap
TOTAL_WEEKS = WEEKS_PER_YEAR + EXTRA_WEEKS_PER_YEAR

# Field structure constants
COLUMNS = 5  # Number of columns per row (smallest planting unit)
NET_ROW_SIZE = 4
FLEECE_ROW_SIZE = 4

# Field layout definition
# Each plot contains blocks, each block contains rows
FIELD = {
    "plots": [
        {"blocks": [{"rows": 5}, {"rows": 2}]},  # PLOT 1
        {"blocks": [{"rows": 7}]},  # PLOT 2
        # Commented out plots can be uncommented when needed
        # {"blocks": [{"rows": 8}] * 4 + [{"rows": 4}] * 2},  # Oak
        # {"blocks": [{"rows": 8}] * 6 + [{"rows": 4}] * 1},  # Pioppo
        # {"blocks": [{"rows": 8}] * 10 + [{"rows": 6}] * 1},  # Walnut
        # {"blocks": [{"rows": 8}] * 6 + [{"rows": 4}] * 1},  # Frassino
    ]
}


# Precompute the number of beds in each block
def get_beds_per_block():
    beds_per_block = []
    for plot in FIELD["plots"]:
        beds_per_block.append([block["rows"] * COLUMNS for block in plot["blocks"]])
    return beds_per_block


# Precompute the cumulative number of beds up to each block
def get_cumulative_beds():
    beds_per_block = get_beds_per_block()
    cumulative_beds = []
    for plot_id, plot in enumerate(FIELD["plots"]):
        plot_cumulative_beds = [0]  # First block starts at bed 0
        for beds in beds_per_block[plot_id]:
            plot_cumulative_beds.append(plot_cumulative_beds[-1] + beds)
        cumulative_beds.append(plot_cumulative_beds)
    return cumulative_beds


# Helper function to find the block containing a given bed
def get_block_id(plot_id, bed_id):
    cumulative_beds = get_cumulative_beds()
    for block_id in range(len(cumulative_beds[plot_id]) - 1):
        if (
            cumulative_beds[plot_id][block_id]
            <= bed_id
            < cumulative_beds[plot_id][block_id + 1]
        ):
            return block_id
    return None


# Optimizer parameters
SOLVER_WORKERS = 8
SOLVER_MAX_TIME_SECONDS = 60 * 60 * 24  # 1 day

# Objective function weights
WEIGHT_TOTAL_PLOTS_USED = 10  # Higher weight for minimizing plot usage
WEIGHT_TOTAL_BLOCKS_USED = 5  # Medium weight for minimizing block usage
WEIGHT_TOTAL_ROWS_USED = 1  # Base weight for minimizing row usage
WEIGHT_ROWS_USED_PER_VSET = 2
WEIGHT_PLANTING_LINE_DISPERSION = 1
WEIGHT_VEGETABLE_SETS_DISTANCE = 2
WEIGHT_FLEECE_COUNT = 10
