# Planning grid — which day's stock do we show?

Context: the planning grid in `PlanningHarvestShares` displays the
column `current_stock_begin_of_week` (visible behind the "detailed
columns" toggle) and, after the stock-only-row work in
`ShareContentService.get_share_content_for_week` /
`_build_stock_only_rows`, synthesizes rows for share articles that have
stock but no `ShareContent` yet.

Both surfaces read from `StockService.get_theoretical_current_stock(...)`
and need a `(year, delivery_week, day_number)` triple to fetch the
right snapshot. The question is which day to use.

The current implementation uses **Sunday of the ISO week preceding the
week being planned** — i.e. for "week 23", we ask for the stock as of
the Sunday that ends week 22. Synthetic stock-only rows and the
existing `current_stock_begin_of_week` field on real rows MUST stay in
sync; whatever the project picks needs to be applied in both places
together.

## Options

### Option 1 — Sunday before the planned week (CURRENT)

Use the Sunday that ends the ISO week preceding the week being viewed.

- **Pros**
  - Matches the existing `current_stock_begin_of_week` semantics on
    real rows — synthetic rows and forecast/plan rows show the same
    number for the same `(article, unit, size)`.
  - Natural for **forward planning** (most of the work the team does):
    "what's on the shelf as week N opens?".
  - Historical-safe: for past weeks the snapshot+movements pipeline
    returns the balance as of that historical Sunday.

- **Cons**
  - **Stale mid-week.** If a planner opens "this week" on Wednesday
    and the team has already sold half the potatoes, the Sunday number
    shows 20 KG while the shelf has 10. Same staleness exists for
    existing rows today — not a new problem.

### Option 2 — Always use "today"

Always feed `timezone.now().date()` into
`get_theoretical_current_stock`.

- **Pros**
  - Always matches what's actually on the shelf right now.

- **Cons**
  - **Diverges from the existing column.** The same article would show
    one stock number on a forecast-attached row (Sunday-of-prev-week,
    per `get_share_content_as_frontend_data`) and another on a
    stock-only synthetic row (today). Confusing.
  - For **past weeks** the column would always show today's stock,
    which is meaningless — retrospective review breaks.
  - Would require also rewriting the stock pull inside
    `get_share_content_as_frontend_data` to stay consistent, doubling
    the touch surface.

### Option 3 — Hybrid: `min(today, Sunday-of-prev-week)`

For future weeks: Sunday-of-prev-week (Option 1).
For the current week: today.
For past weeks: the historical Sunday-of-prev-week (Option 1 path).

- **Pros**
  - Optimises each viewing mode for what's most useful: forward
    planning gets the consistent week-start snapshot; the current week
    gets a live read.

- **Cons**
  - Subtle rule, harder to explain in the UI tooltip.
  - Still has to be applied to both real and synthetic rows in lock-
    step or the divergence in Option 2 re-appears for the current-week
    case.

## Recommendation

Stick with **Option 1** until a planner explicitly complains about
mid-week staleness. The win — consistency between real and synthetic
rows — outweighs the staleness, especially because that staleness
already exists for the column on existing rows.

If the team eventually wants live mid-week numbers, prefer **Option 3**
over Option 2: keep historical and future behaviour the same as today,
just add a special case for the current week. Make the same swap in
both:

- `ShareContentService.get_share_content_as_frontend_data` (the stock
  fetch around the `monday = Week(yr, dw).day(0)` block)
- `ShareContentService._build_stock_only_rows` (the same Week / sunday
  / `get_theoretical_current_stock` calls)

## Code references

- `apps/commissioning/services/share_content_service.py`
  - `get_share_content_as_frontend_data` — stock fetch used for the
    `current_stock_begin_of_week` field on existing rows.
  - `_build_stock_only_rows` — stock fetch used to synthesize rows for
    articles with stock but no `ShareContent`.
- `apps/commissioning/services/stock_service.py`
  - `StockService.get_theoretical_current_stock` — the underlying
    snapshot+movements aggregation.
- Frontend: `src/hooks/columns/usePlanningHarvestSharesColumns.tsx`
  - The `current_stock_begin_of_week` column is currently gated behind
    `showDetailedColumns`; the colour ladder picks up the
    `is_stock_only` flag from the backend.
