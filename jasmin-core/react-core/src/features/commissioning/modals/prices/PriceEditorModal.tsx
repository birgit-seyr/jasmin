import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { Modal, Spin } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import {
  useCallback,
  useMemo,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { EditableTable, gatedByPermission, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DateRangeStatusLegend } from "@shared/ui";
import { useRoles } from "@shared/auth";
import { useInvalidateAfterTableMutation } from "@hooks/index";

type ListHookResult<T> = {
  data: T[] | undefined;
  isLoading: boolean;
  isFetching: boolean;
};

type ListHook<T, P extends Record<string, string>> = (
  params: P,
  options: { query: { enabled: boolean } },
) => ListHookResult<T>;

type GetListQueryKey<P extends Record<string, string>> = (
  params: P,
) => QueryKey;

export interface PriceModalApi<TCreate, TUpdate = TCreate> {
  create: (data: TCreate) => Promise<unknown>;
  partialUpdate: (id: string, data: TUpdate) => Promise<unknown>;
  destroy: (id: string) => Promise<unknown>;
}

export interface PriceEditorModalProps<T, TCreate, TUpdate = TCreate> {
  visible: boolean;
  onClose: () => void;
  title: ReactNode;
  width?: number | string;
  style?: CSSProperties;
  /** These price modals are always opened from inside a parent config modal
   *  (sibling modals get no AntD nesting auto-lift), so default above 1000. */
  zIndex?: number;

  /** Foreign-key field name (e.g. "crate", "share_article"). */
  fkField: string;
  /** Foreign-key value passed to list hook + injected on save. */
  fkValue: string | null;

  /** Default tax-rate to inject when adding a new row (key === -1). */
  defaultTaxRate?: number;

  columns: EditableColumnConfig[];

  listHook: ListHook<T, Record<string, string>>;
  getListQueryKey: GetListQueryKey<Record<string, string>>;
  api: PriceModalApi<TCreate, TUpdate>;
}

/**
 * Generic editor modal for price/time-bound records keyed by a single FK.
 * Encapsulates the shared shell used by Crate / ExtraArticle / ShareArticle /
 * ShareTypeVariation price modals.
 */
export default function PriceEditorModal<T, TCreate, TUpdate = TCreate>({
  visible,
  onClose,
  title,
  // Fixed default (NOT ``max-content``): an AntD Modal sized to content
  // feedback-loops with the inner table's ResizeObserver and creeps ever
  // wider. Callers pass their own fixed width; this is the fallback.
  width = 700,
  style,
  zIndex = 1100,
  fkField,
  fkValue,
  defaultTaxRate,
  columns,
  listHook,
  getListQueryKey,
  api,
}: PriceEditorModalProps<T, TCreate, TUpdate>) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isOffice),
      canDeleteRecord: (record: TableRecord) => {
        if (record.key === -1 || !record.id) return true;
        return (record as Record<string, unknown>).can_be_deleted !== false;
      },
    }),
    [isOffice],
  );

  const listParams = useMemo(
    () => ({ [fkField]: fkValue ?? "" }) as Record<string, string>,
    [fkField, fkValue],
  );

  // Outer Spin uses ``loading`` (isLoading → first paint only); the table's
  // ``loading`` uses ``isFetching`` so reopening for a previously-viewed FK
  // (cached under the global staleTime:0) shows a grid refresh spinner while
  // the list refetches, instead of silently swapping the rows.
  const { data: rawData, isLoading: loading, isFetching } = listHook(listParams, {
    query: { enabled: visible && !!fkValue },
  });

  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: getListQueryKey(listParams) });
  }, [queryClient, getListQueryKey, listParams]);
  const { onSaveSuccess: trackRecentlyAdded, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  // A price save shifts the TimeBoundMixin succession: creating a price (or
  // moving an existing one's valid_from) re-closes the NEIGHBOURING price's
  // valid_until. That downstream change lives on the same list query but a
  // DIFFERENT row than the one EditableTable inserts locally, so we must refetch
  // to surface it — otherwise the predecessor keeps its old (open) valid_until
  // until a manual reopen. ``useInvalidateAfterTableMutation`` deliberately
  // skips create/update invalidation for big list pages; small time-bound
  // modals are the documented carve-out. We still thread through
  // ``trackRecentlyAdded`` for the recentlyAddedIds pin bookkeeping.
  const onSaveSuccess = useCallback(
    (record: TableRecord, action: "create" | "update") => {
      trackRecentlyAdded(record, action);
      invalidateData();
    },
    [trackRecentlyAdded, invalidateData],
  );

  const customEdit = useCallback(
    (record: TableRecord) => {
      if (record.key === -1 && defaultTaxRate != null) {
        return { ...record, tax_rate: defaultTaxRate };
      }
      return record;
    },
    [defaultTaxRate],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      [fkField]: fkValue,
    }),
    [fkField, fkValue],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions({
        create: (d) => api.create(d as unknown as TCreate),
        update: (id, d) => api.partialUpdate(id, d as unknown as TUpdate),
        delete: (id) => api.destroy(id),
      }),
    [api],
  );

  return (
    <Modal
      title={title}
      open={visible}
      onCancel={onClose}
      width={width}
      zIndex={zIndex}
      style={style}
      // Unmount the table on close so reopening for a DIFFERENT variation
      // starts fresh — no carry-over of the previous variation's rows, draft,
      // or recentlyAddedIds pins.
      destroyOnHidden
      footer={[
        <ModalCloseFooter key="close" onClose={onClose} />,
      ]}
    >
      {loading ? (
        <div className="loading-placeholder">
          <Spin size="large" />
          {/* AntD wires aria-live on the Spin, but with no text child it
              announces nothing — give the live region readable status text. */}
          <span className="sr-only" role="status">
            {t("common.loading")}
          </span>
        </div>
      ) : (
        <>
          {t("commissioning.prices_are_netto")}
          <EditableTable
            columns={columns}
            apiFunctions={apiFunctions}
            initialData={data}
            loading={isFetching}
            onSaveSuccess={onSaveSuccess}
            onDeleteSuccess={onDeleteSuccess}
            permissions={permissions}
            customSave={customSave}
            customEdit={customEdit}
            forceInlineMode={true}
            pagination={true}
            scroll={{ x: "max-content" }}
          />
          <DateRangeStatusLegend />
        </>
      )}
    </Modal>
  );
}
