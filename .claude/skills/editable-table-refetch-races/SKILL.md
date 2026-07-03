---
name: editable-table-refetch-races
description: How EditableTable keeps optimistic add/delete in sync with a parent TanStack query under the global staleTime=0 — recentlyAddedIds (pin) and recentlyDeletedIds (filter) guard the initialData-sync effect against a refetch that raced ahead of the backend. Use when touching EditableTable's data sync, debugging a row that "disappears after save until refresh" or "flickers/reappears on delete," or wiring a page that owns its data via initialData.
---

# EditableTable ⇄ refetch races

## Setup that causes them

`staleTime: 0` + `refetchOnWindowFocus: true` (set globally in `app/App.tsx`)
means a page's list query refetches constantly. When a page **owns its data**
(passes `initialData={query.data}`, no `apiFunctions.list`), EditableTable
mirrors that prop into internal state via a `useEffect` that fires on every
`initialData` reference change
(`src/shared/tables/BasicEditableTable/EditableTable.tsx`).

The component ALSO mutates its own state optimistically on save/delete
(`useEditableTable.ts`: `setData(...)`). So there are two writers to the same
table state, and a refetch can land carrying a snapshot that **raced ahead of
the backend** (POST/DELETE not yet visible to a concurrent GET). Re-syncing
that stale snapshot fights the optimistic mutation. Two symptoms:

- **Add:** save a new row → optimistic insert → a refetch that predates the
  POST arrives → sync overwrites local state with a list that lacks the new
  row → "row saved but not shown until I refresh."
- **Delete:** delete a row → optimistic removal → a refetch that predates the
  DELETE arrives (new `initialData` *reference*, stale pre-delete *content*,
  e.g. from the parent re-rendering on the invalidate's `isFetching` toggle) →
  sync re-adds the row → it **flickers back in**, then the delete-triggered
  refetch settles and removes it again.

## The two guards (keep them symmetric)

`useEditableTable` tracks, per mount:

- `recentlyAddedIds` — ids saved this mount. The sync effect **pins** these to
  the top and **reaches into previous local state** to keep a just-added row
  that the refetch doesn't include yet.
- `recentlyDeletedIds` — ids deleted this mount. The sync effect **filters
  these out** of `initialData` so a stale refetch can't re-introduce a deleted
  row.

Both are read inside the sync effect via a **ref** (`recentlyAddedIdsRef` /
`recentlyDeletedIdsRef`), NOT via the effect's dependency array — otherwise
updating them (right after the optimistic `setData`) would retrigger the
effect with the still-stale `initialData` and reproduce the very race. The
effect's deps stay `[initialData, setDataWithTransform, pinNewRowsToTop]`.

Neither set is cleared: ids are unique nanoids that never recur, so once the
backend catches up the refetch naturally stops including a deleted id /
starts including an added id, and the guard becomes a no-op.

The `{ key: -1 }` draft row is preserved across syncs by `preserveDraft` for
the same reason (an in-flight add mustn't be wiped by a refetch).

## When adding a new optimistic mutation

If you add another optimistic local mutation to EditableTable, ask: "can a
refetch that predates my backend write land and undo it?" If yes, it needs the
same ref-guarded treatment in the `initialData`-sync effect. Don't put the
tracking state in the effect's deps.

## Data-ownership reminder (don't reintroduce a double fetch)

A page either lets the table own its data (`apiFunctions.list` +
`showSearchBar`, empty `initialData`) OR owns it itself (a `use*List` query →
`initialData={data}`, and NO `list` in `apiFunctions`). Passing both makes the
table auto-fetch the same endpoint a second time with two racing `setData`
paths — see CLAUDE.md "EditableTable data ownership."
