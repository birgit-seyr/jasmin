import type { FormInstance } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useInvalidateAfterTableMutation } from "@hooks/index";

import type {
  ApiFunctions,
  EditableTableProps,
  TablePermissions,
  TableRecord,
} from "./BasicEditableTable/types";
import { wrapApiFunctions } from "./BasicEditableTable/wrapApiFunctions";

/** Minimal slice of an Orval `useQuery` result the CRUD list page reads. */
interface ListQueryResult {
  data?: unknown;
  isLoading: boolean;
  isFetching: boolean;
}

/**
 * The generated API surface for one CRUD resource: the list hook, the three
 * mutation fns, and the list query key (for invalidation). This is the ONE
 * genuinely per-resource bit that can't be derived — bundle the Orval symbols
 * here (ideally as a module-level const so its identity is stable).
 */
export interface CrudResource<TRow extends TableRecord> {
  // `any[]` (not `unknown[]`) so the heterogeneous Orval hook/query-key
  // signatures (each with its own typed `*ListParams`) stay assignable — a
  // rest of `unknown` would fail param contravariance against them.
  useList: (...args: any[]) => ListQueryResult;
  create: (payload: TRow) => Promise<unknown>;
  update: (id: string, payload: TRow) => Promise<unknown>;
  delete: (id: string, extra?: Record<string, unknown>) => Promise<unknown>;
  getListQueryKey: (...args: any[]) => readonly unknown[];
}

export interface UseCrudListPageOptions<TRow extends TableRecord> {
  /** The generated list hook + CRUD fns + query key. */
  resource: CrudResource<TRow>;
  /** Table permissions (caller picks the helper — `permissionsWithDeletable`,
   *  `gatedByPermissionOnlyEdit`, …; the choice legitimately varies per page). */
  permissions: TablePermissions<TRow>;
  /** Render + wire the "hide inactive" switch and active filter. Default
   *  true; pass false for resources without an active flag (e.g. Storages). */
  withHideInactive?: boolean;
  /** The boolean row field the hide-inactive filter reads. Default
   *  `"is_active"`; some resources use a scoped flag (e.g. `"is_active_seller"`). */
  activeField?: string;
  /** Values stamped onto the new row (`customEdit` for the `key === -1` draft).
   *  Default `{ is_active: true }`. Pass a stable object or omit. */
  newRowDefaults?: Record<string, unknown>;
  /** Optional params forwarded to the list hook (which cached query to fetch).
   *  Invalidation always targets the resource's BASE list key, which
   *  prefix-matches this params query too — so a scoped list still refreshes. */
  listParams?: unknown;
}

/** Everything {@link useCrudListPage} returns — also the shape handed to the
 *  render-prop slots of {@link import("./CrudListPage").CrudListPage}. */
export interface CrudListPageApi<TRow extends TableRecord> {
  permissions: TablePermissions<TRow>;
  /** Unfiltered rows (for CSV export of everything). */
  data: TRow[];
  /** Rows after the active filter — feed this to `initialData`. */
  filteredData: TRow[];
  isLoading: boolean;
  isFetching: boolean;
  apiFunctions: ApiFunctions;
  onSaveSuccess: EditableTableProps<TRow>["onSaveSuccess"];
  onDeleteSuccess: EditableTableProps<TRow>["onDeleteSuccess"];
  invalidate: () => void;
  customEdit: (record: TRow, form: FormInstance) => TRow;
  /** Whether the page should render the hide-inactive switch. */
  showHideInactive: boolean;
  hideInactive: boolean;
  setHideInactive: (value: boolean) => void;
}

const DEFAULT_NEW_ROW_DEFAULTS: Record<string, unknown> = { is_active: true };

/**
 * Owns the boilerplate every commissioning `List*` page repeats verbatim:
 * page-owned data (list hook → `initialData`, never `apiFunctions.list`, so no
 * double fetch), the `is_active` hide-inactive filter, cache invalidation on
 * mutation, `wrapApiFunctions` CRUD, and the `customEdit` new-row defaults.
 * Returns everything the page hands to `EditableTable`; the page keeps only its
 * columns and any page-specific extras (modals, CSV, header actions).
 *
 * See {@link CrudListPage} for the thin component wrapper (pure-skeleton pages);
 * complex pages call this hook directly and render their own JSX.
 */
export function useCrudListPage<TRow extends TableRecord>({
  resource,
  permissions,
  withHideInactive = true,
  activeField = "is_active",
  newRowDefaults = DEFAULT_NEW_ROW_DEFAULTS,
  listParams,
}: UseCrudListPageOptions<TRow>): CrudListPageApi<TRow> {
  const queryClient = useQueryClient();
  const [hideInactive, setHideInactive] = useState(true);

  const query = resource.useList(listParams);
  const isLoading = query.isLoading;
  const isFetching = query.isFetching;

  const data = useMemo(
    () => (query.data ?? []) as unknown as TRow[],
    [query.data],
  );
  const filteredData = useMemo(
    () =>
      withHideInactive && hideInactive
        ? data.filter((row) => (row as Record<string, unknown>)[activeField])
        : data,
    [data, hideInactive, withHideInactive, activeField],
  );

  const invalidate = useCallback(() => {
    // Base list key (no params) — invalidateQueries prefix-matches, so a
    // params-scoped list (e.g. { is_seller: true }) still refreshes, and any
    // sibling scope on the same endpoint is refreshed too rather than left stale.
    queryClient.invalidateQueries({ queryKey: resource.getListQueryKey() });
  }, [queryClient, resource]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidate);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<TRow>({
        create: (payload) => resource.create(payload),
        update: (id, payload) => resource.update(id, payload),
        delete: (id, extra) => resource.delete(id, extra),
      }),
    [resource],
  );

  const customEdit = useCallback(
    (record: TRow, form: FormInstance): TRow => {
      if (record.key === -1) {
        form.setFieldsValue(newRowDefaults);
        return { ...record, ...newRowDefaults };
      }
      return record;
    },
    [newRowDefaults],
  );

  return {
    permissions,
    /** Unfiltered rows (for CSV export of everything). */
    data,
    /** Rows after the hide-inactive filter — feed this to `initialData`. */
    filteredData,
    isLoading,
    isFetching,
    apiFunctions,
    onSaveSuccess,
    onDeleteSuccess,
    invalidate,
    customEdit,
    /** Whether the page should render the hide-inactive switch. */
    showHideInactive: withHideInactive,
    hideInactive,
    setHideInactive,
  };
}
