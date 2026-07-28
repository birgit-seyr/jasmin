"""Serpentine (boustrophedon) cell indexing.

The optimizer works in a plain linear cell index ``0..N`` per plot; contiguity in
that index is what the solver enforces. The *serpentine* interpretation lives
here: the tractor drives one bed to its end, then the next bed back-to-front, so
consecutive linear cells follow the tractor path. Physical position is derived
from the linear index for display / layout only — the solver never needs it.

Because the serpentine map is a fixed permutation of a plot's cells, two linear
ranges overlap iff their physical cells overlap. That is what lets crop rotation
be checked directly on the stored ``start_cell`` ranges across years, without
decoding to physical positions (as long as a plot's bed count is stable).
"""


def physical_cell(linear_index: int, cells_per_bed: int) -> tuple[int, int]:
    """Map a linear (serpentine) cell index to ``(bed, offset_within_bed)``.

    Even beds run front-to-back, odd beds back-to-front, so a contiguous run of
    linear cells traces the tractor's path.
    """
    bed, offset = divmod(linear_index, cells_per_bed)
    if bed % 2 == 1:
        offset = cells_per_bed - 1 - offset
    return bed, offset


def linear_index(bed: int, offset: int, cells_per_bed: int) -> int:
    """Inverse of :func:`physical_cell`."""
    if bed % 2 == 1:
        offset = cells_per_bed - 1 - offset
    return bed * cells_per_bed + offset
