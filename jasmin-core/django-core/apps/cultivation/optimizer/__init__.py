"""Cultivation placement optimizer (CP-SAT, interval formulation).

Replaces the per-cell / per-week boolean model in ``optimizer_folder`` with
OR-Tools interval variables + ``AddNoOverlap2D`` (space × time). Each batch is a
single contiguous run of cells within one plot; the solver decides *which* plot
and *where* (the start cell). Contiguity is free (it is what an interval var is),
and no-overlap-2D means "no two batches share a cell in the same week", which
lets crops succeed each other on the same cells across the season.

The whole thing works in a plain linear cell index per plot; the serpentine
(tractor-path) interpretation lives in :mod:`serpentine` and is only applied when
decoding a placement back to a physical position — the solver never needs it.

Running the optimizer requires OR-Tools, kept as an optional research dependency
(not in ``pyproject.toml``, same as the ``solver/`` code): ``pip install ortools``.
"""

from typing import TYPE_CHECKING

__all__ = ["CultivationPlanOptimizer", "optimize_year"]

if TYPE_CHECKING:
    from .optimizer import CultivationPlanOptimizer, optimize_year


# Lazy so the pure helpers (serpentine, config) and the DB loaders stay
# importable without OR-Tools installed — only reaching for the solver entry
# points pulls it in.
def __getattr__(name: str):
    if name in __all__:
        from . import optimizer

        return getattr(optimizer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
