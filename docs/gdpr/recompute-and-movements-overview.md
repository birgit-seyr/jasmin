# Stock, movements & recompute — how it all fits together

A plain-language map of how `MovementShareArticle` (the stock ledger) is built and
kept correct in `apps/commissioning`: the recompute chains, the theoretical vs
actual vs INVENTORY movements, the snapshot/balance projections, and the invariants
that hold them together. Reflects the code after the 2026-06 soundness work.

---

## TL;DR

- **`MovementShareArticle` is the append-only stock ledger.** Current stock for an
  entity = `(share_article, unit, size, storage)` is `SUM(amount)` of its rows.
- **Movements are *derived*, not edited in place.** When a demand input changes, the
  affected planning rows are **wiped and rebuilt** by a *recompute*
  (`recompute_shares` member side, `recompute_order_contents` reseller side).
- **Two cached read-models** sit on top for speed: `StockSnapshot` (point-in-time
  baselines) and `CurrentStockBalance` (the maintained "now" row per entity).
- **The golden rule:** any op that mutates a `ShareContent`, `ShareDelivery`, or
  `Forecast` (or anything feeding their demand) MUST call `recompute_shares` at the
  end, inside the same transaction.

---

## 1. The ledger — `MovementShareArticle`

One row = "**N units of article A (unit/size U/S) moved in/out of storage X on date
D**". `movement_type` tags *why*:

| `movement_type` | `is_theoretical` | Source FK | Meaning |
|---|---|---|---|
| `SHARECONTENT` | no | `share_content` | a member share's consumption (outflow) |
| `ORDERCONTENT` | no | `order_content` | a reseller order's consumption (outflow) |
| `HARVEST` | **yes** | `theoretical_harvest` | planned harvest inflow |
| `PURCHASE` | **yes** | `theoretical_purchase` | planned external purchase inflow |
| `WASH` / `CLEAN` | **yes** | `theoretical_wash_amount` / `…clean…` | planned long→short transfer (a *pair*) |
| `HARVEST` / `PURCHASE` | no | `harvest` / `purchase` | the **actual** recorded harvest/purchase |
| `WASTE` | no | `waste` | recorded waste (always `−abs(amount)`) |
| `INVENTORY` | no | *(all source FKs NULL)* | a **manual physical count** (*Bestand*) |

A DB `CheckConstraint` enforces **exactly one** source FK on non-`INVENTORY` rows.
So a **theoretical** HARVEST movement carries `theoretical_harvest` and has
`share_content`/`order_content` = **NULL** — reach it via its `Theoretical*` parent's
`share_content`/`order_content` link, *not* a `share_content__in` filter.

`Theoretical*` → movement FKs are `on_delete=CASCADE`, so deleting a theoretical
deletes its movement. `SHARECONTENT`/`ORDERCONTENT` movements point at a still-living
row, so a recompute deletes them explicitly.

---

## 2. The two read-models (CQRS-lite)

- **`StockSnapshot`** — a balance baseline at a point in time, per entity. Created
  **only** at INVENTORY-count dates (directly, or rebuilt during a cascade).
  `compute_balance` finds the latest snapshot `≤ the date you want` and sums only the
  movements after it — so it never rescans the whole history.
- **`CurrentStockBalance`** — one maintained "now" row per entity, read by the
  DocumentationCurrentStock page. Refreshed by `CurrentBalanceService.recompute_for_entity`
  at the end of every cascade. `reconcile_current_stock --fix` repairs drift.

```
MovementShareArticle (append-only ledger)  ← source of truth
   ├──► StockSnapshot       — baselines at INVENTORY dates (fast any-date lookup)
   └──► CurrentStockBalance — one "now" row per entity (fast current-stock page)
```

**Timestamp convention** keeps the two consistent: operational movements (harvest,
wash, sharecontent…) are at **noon**; INVENTORY counts + their snapshots at **23:00**.
A count is baked into its snapshot and skipped exactly once when that snapshot is used
as a baseline — no double/zero count.

---

## 3. The recompute pipeline (`recompute_for_shares`)

`ShareContentService.recompute_for_shares(share_ids)` (one `@transaction.atomic`,
`select_for_update` on the shares), in order:

1. **Capture old movements** — SHARECONTENT rows **and** the theoretical
   HARVEST/PURCHASE/WASH/CLEAN movements (via `theoretical_*__share_content__in`),
   *before* anything is deleted.
2. **Wipe** the `Theoretical*` rows (their movements cascade away) + the SHARECONTENT
   movements (explicit delete).
3. **Rebuild** from current demand: `create_all_theoretical_objects` (new theoreticals
   + their movements, and `cascade_for_movements` over them so a pre-existing snapshot
   can't shadow them), then `create_movements` (new SHARECONTENT movements, stock-allocated).
4. **Cascade the old movements** — `cascade_for_movements(old_movements)` compensates
   every storage a zeroed/relocated movement stranded (content **and** theoretical).
5. **Re-derive actual corrections for the old dimensions** —
   `recalculate_actual_corrections(old_movements)` so an actual harvest/purchase whose
   theoreticals dropped/relocated re-derives to `counted` (see §6).

The reseller side (`recompute_for_order_contents`) is the mirror image (ORDERCONTENT
movements, `theoretical_*__order_content__in`).

---

## 4. The `recompute_shares` contract

- **Idempotent** wipe-and-rebuild — calling twice yields the same state.
- **Run it LAST, inside the caller's transaction.** It re-raises on failure, so wrapping
  *mutation + recompute* in one `transaction.atomic()` rolls the mutation back if the
  recompute fails (no committed-row-with-stale-planning split).
- **Virtual → physical fan-out:** a Share on a *virtual* variation has no ShareContent;
  `recompute_shares` auto-adds the physical-variation shares it feeds (same year/week/day).
- **Bulk paths bypass `save()`** (`bulk_create`/`update()`/raw SQL) — call
  `recompute_shares` explicitly there.

**Deferred variant** `recompute_shares_async` (Huey `@db_task`, retries+re-raise) is
used **only** by the forecast write path so the office save returns fast. *Known
accepted limitation:* a task that is **never dispatched** (broker down at `on_commit`,
queue purge, crash in the dispatch window) has no convergence backstop — Redis
`--appendonly` covers the common case, the window is narrow, nothing is corrupted
(empty/stale harvest only), and it self-heals on the next edit. Backstop options if it
ever bites: a nightly reconciliation `@db_periodic_task`, or a synchronous update path.

---

## 5. Who calls `recompute_shares`

| Caller | Trigger |
|---|---|
| `ShareDeliveryViewSet` create/update/destroy + `create_manual_entry` | office edits a delivery |
| `ShareDeliveryOverviewViewSet` create/update/destroy | office edits on the Abos › ShareDeliveries grid |
| `ShareContentViewSet` create/update/destroy | office edits a `ShareContent` |
| `OptinService.toggle` | on/off box `is_opted_in` toggled |
| `SubscriptionService` confirm / cancel | subscription materialised / cancelled |
| `ShareContentService.replace_/delete_share_planning`, `DefaultShareContentService` | planning / default-content edits |
| `ForecastService` (create/update/bulk-copy) | a forecast changes — **deferred** via `on_commit` |
| `share_import_service`, `shares_delivery_day_service` | bulk import / day reassignment |
| `VirtualComponentsViewSet.create` | virtual-variation component config rewritten |

(Reseller mirror: `recompute_order_contents` from `OrderContentService` create/update.)

All write hooks wrap mutation + recompute in one `transaction.atomic()`; the
ShareContent-delete hook also captures + cascades the deleted row's movements (which
the rebuild can't see).

---

## 6. The correction model — does it re-adjust?

Actual harvest/purchase counts and INVENTORY counts both use the **same trick**: store
the real absolute value in `counted_amount`, store a *delta* in `amount`, and re-derive
the delta when the surroundings shift. Both re-adjust **by design**:

### Actual harvest/purchase (correction mode, short-term storage)
`amount = counted − Σtheoretical`; the ledger then totals to the real `counted`. When a
recompute rebuilds the theoreticals, `recalculate_actual_corrections` re-derives
`amount = counted − Σtheoretical_new` — including the case where the theoreticals
**dropped to zero** or **relocated** (the recompute feeds it the *old* dimensions too),
so the entity total stays `= counted`. (Off short-term storage it's a plain `amount =
raw` movement, no correction.)

### INVENTORY (manual count)
`amount = counted_amount − balance_before`. When an earlier movement changes,
`cascade_future_inventories` walks every later INVENTORY forward and re-derives each
delta from its `counted_amount`, preserving the absolute count. The single-entry **and**
the bulk endpoints (finalize / set-as-expected / set-to-zero) now both cascade.

> *One-liner:* a recorded count is never silently lost — the correction part moves so the
> real number you entered is preserved, whatever changes around it.

---

## 7. Invariants worth knowing

1. **A `ShareContent` linked to a `Forecast` must match it on `share_article`, `unit`,
   `size`** (`ShareContent._validate_forecast_dimensions`, enforced in `clean()`+`save()`).
   The forecast is that content's harvest-planning source, so the theoretical harvest
   (on the forecast) and the actual-harvest correction (on the content) must sit on the
   same ledger dimension — otherwise the produce double-counts. (`harvest_size` =
   content size.) **Deploy note:** any existing ShareContent whose forecast diverges
   would fail its next `save()` — reconcile such rows before deploying.
2. **Harvest storage follows `comes_from_long_term_storage`** (`Storage.select_harvest`):
   `comes_from_long_term=True` → the harvest deposits to **long-term**; a washed/cleaned
   line is then moved to short-term by the WASH/CLEAN transfer pair (`−long_term`,
   `+short_term`), which nets long-term to zero. (Depositing a washed long-term line
   straight to short-term would double-count it and leave a phantom negative on
   long-term.) *Edge:* if `comes_from_long_term` is set but no long-term storage is
   configured, the harvest lands on `None` — a misconfiguration to guard at the config
   layer.
3. **Capture old movements before a wipe, cascade them after the rebuild** — old storages
   keep stale projections otherwise.
4. **Bulk paths bypass `save()`/`clean()`** — enforce invariants explicitly there.

---

## 8. Downstream flow — what fires when X changes

### `ShareContent` create / update / delete
→ `recompute_shares([share_id])` → the §3 wipe-and-rebuild (theoreticals + their
movements, SHARECONTENT movements, cascades, correction re-derive). Delete also cascades
the deleted row's own movements.

### `ShareDelivery` create / update / delete
→ `recompute_shares([share_id])`. A delivery is **demand** (add/remove, `joker_taken`,
`is_opted_in`, `delivery_station_day`); changing it changes the ShareContent totals → the
same rebuild. Virtual-variation deliveries fan out to the physical shares they feed.

### `OrderContent` create / update / delete
→ `recompute_order_contents([oc_id])` — the reseller mirror (ORDERCONTENT movements).

### `Forecast` create / update / delete
→ `ForecastService` → **deferred** `recompute_shares_async`. Update wipes the forecast's
`TheoreticalHarvest` then rebuilds. The forecast sets each ShareContent's harvest
size/storage/days.

### `Harvest` / `Purchase` / `Waste` / `WashAmount` / `CleanAmount` (ACTUALS)
→ `GenericDocumentationService` (NOT a recompute — real-world records). Create →
`_create_movement` (correction mode on short-term: `amount = counted − Σtheoretical`,
else plain) + `cascade_for_movements`. Update → `_upsert_movement` (delete+recreate +
cascade both old & new entities). Delete → the movement FK-cascades away.

### Inventory via **CurrentStock** (`INVENTORY` movement)
→ `views/stock_views.py`: create the INVENTORY movement (`amount = counted −
balance_before`, `counted_amount` = the count) + a snapshot + `cascade_future_inventories`
+ `CurrentStockBalance` refresh. Touches **no** theoretical/harvest objects — an INVENTORY
count is an independent absolute anchor on the ledger.

---

## 9. Known deferred / accepted items

- **Forecast recompute has no convergence backstop** for a never-dispatched task (§4) —
  *accepted* (narrow, self-healing, no corruption).
- **Rebuild-time correction recalc takes no advisory lock** — a concurrent
  actual-record + recompute *could* race on the same dimension (Low/uncertain). A lock
  was tried and **reverted** because it introduced a deadlock with the `ShareArticle`
  row lock; a correct fix needs a single sorted pass over old∪new dimensions before
  `create_movements`. Left as-is.
- **Season-wide recompute performance** (cumulative per-week ledger scans; multiple
  uncoordinated cascade passes; per-week placeholder writes; the long lock window).
  *Deferred.* Note the soundness work (capture+cascade old theoreticals, cascade new
  theoreticals, old-dimension recalc) **adds** cascade passes, so coalescing them into
  one terminal cascade is more worthwhile now.
