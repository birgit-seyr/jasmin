import type { Key } from "react";
import { useCallback, useMemo, useState } from "react";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

/**
 * Returns a pair of ``EditableTable`` callbacks that invalidate the
 * underlying list query ONLY on delete. Saves — both CREATE and
 * UPDATE — leave the local state ``EditableTable`` already maintains
 * untouched.
 *
 * Mutation policy:
 *
 *   * CREATE → no invalidate. The API response carries the saved
 *     row; ``EditableTable`` inserts it at the top (where the "+ Add
 *     row" placeholder sat) and tracks the new id in its internal
 *     ``recentlyAddedIds`` pin (default ``pinNewRowsToTop=true``).
 *     For large list pages (Members, Abos, ListShareArticles, ...)
 *     a per-save full refetch is expensive — and unnecessary, because
 *     the local-state update already shows the office what they just
 *     created.
 *   * UPDATE → no invalidate. Same as CREATE: the API response is
 *     the truth for that row, ``EditableTable`` replaces it in-place
 *     in local state. A refetch here would re-apply the backend's
 *     default ordering and yank the just-edited row out from under
 *     the office mid-flow ("rows spring around").
 *   * DELETE → invalidate. The row needs to disappear from the
 *     table and from pagination totals; refetch is the safe default.
 *
 * **Modals or small forms where a saved row's child relations also
 * change** (e.g. ``ShareTypeVariationModal`` showing prices that
 * live on a separate query) need a refetch on create to see those
 * downstream effects. Those callers provide their own
 * ``onSaveSuccess`` that invalidates on ``action === "create"`` and
 * passes through to this hook's ``onSaveSuccess`` for the
 * ``recentlyAddedIds`` bookkeeping. See ``InvoiceModal``,
 * ``DeliveryNoteModal`` and ``ShareTypeVariationModal`` for the
 * canonical pattern.
 *
 * Wire it on a page::
 *
 *     const invalidate = useCallback(() => {
 *       queryClient.invalidateQueries({ queryKey: listQueryKey });
 *     }, [queryClient, listQueryKey]);
 *     const { onSaveSuccess, onDeleteSuccess } =
 *       useInvalidateAfterTableMutation(invalidate);
 *     <EditableTable
 *       onSaveSuccess={onSaveSuccess}
 *       onDeleteSuccess={onDeleteSuccess}
 *       ...
 *     />
 *
 * **Do not** also pass ``onDataChange={invalidate}`` — that fires
 * after every local-state change (every keystroke during inline
 * edit) inside ``EditableTable`` and produces a refetch storm. The
 * save / delete success callbacks are the right level of
 * granularity.
 *
 * If a page needs to do something extra on save (e.g. refetch a
 * sibling query that this list doesn't cover, or deliberately
 * SKIP invalidation for an interactive grid where mid-flow
 * reordering would break the planner's flow), provide a custom
 * ``onSaveSuccess`` — see ``PlanningHarvestSharesBase`` for an
 * example that does NOT invalidate on normal saves (only on the
 * cleared-placeholder edge case).
 */
export function useInvalidateAfterTableMutation(invalidate: () => void) {
  // Track freshly-created row ids so pages that put a custom column
  // sort on the table (e.g. ``Abos.tsx`` with ``defaultSortOrder:
  // "descend"`` on the admin-status column) can keep newly-added rows
  // pinned at the top. ``EditableTable`` already pins them in the data
  // array, but Ant Design's column-level sorter overrides that order
  // on every render. The fix is for the sorter to be aware of the
  // pinned ids; this hook is the natural place to surface them since
  // it already owns the save-success knowledge.
  //
  // Wiring on the consumer:
  //
  //     const { onSaveSuccess, onDeleteSuccess, recentlyAddedIds } =
  //       useInvalidateAfterTableMutation(invalidate);
  //     const wrappedSorter = useCallback(
  //       (a, b, order) => {
  //         const aPin = recentlyAddedIds.has(String(a.id));
  //         const bPin = recentlyAddedIds.has(String(b.id));
  //         if (aPin && !bPin) return order === "descend" ? 1 : -1;
  //         if (!aPin && bPin) return order === "descend" ? -1 : 1;
  //         return baseSorter(a, b, order);
  //       },
  //       [recentlyAddedIds, baseSorter],
  //     );
  //
  // Pages that don't custom-sort can ignore ``recentlyAddedIds``
  // entirely — ``EditableTable``'s built-in pin still works for them.
  const [recentlyAddedIds, setRecentlyAddedIds] = useState<Set<string>>(
    () => new Set(),
  );

  const onSaveSuccess = useCallback(
    (record: TableRecord, action: "create" | "update") => {
      if (action === "create" && record.id != null) {
        const id = String(record.id);
        setRecentlyAddedIds((prev) => {
          if (prev.has(id)) return prev;
          const next = new Set(prev);
          next.add(id);
          return next;
        });
      }
      // Intentional no-op for the row-mutation itself —
      // EditableTable owns the local-state update. See the docstring
      // above for the rationale (and for the
      // modals-need-create-invalidate carve-out).
    },
    [],
  );

  const onDeleteSuccess = useCallback(
    (key: Key) => {
      // Drop deleted ids from the pinned set so the same id (if reused
      // by the backend) isn't accidentally pinned later.
      const id = String(key);
      setRecentlyAddedIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      invalidate();
    },
    [invalidate],
  );

  return useMemo(
    () => ({ onSaveSuccess, onDeleteSuccess, recentlyAddedIds }),
    [onSaveSuccess, onDeleteSuccess, recentlyAddedIds],
  );
}
