import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  commissioningDefaultShareArticlesInShareBulkUpsertCreate,
  getCommissioningDefaultShareArticlesInShareListQueryKey,
  useCommissioningDefaultShareArticlesInShareList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  DefaultShareArticleInShare,
  DefaultShareArticleInShareBulkEntry,
  DefaultShareArticleInShareBulkUpsertRequest,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { EditableTable } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { gatedByPermissionOnlyEdit } from "@shared/tables/tablePermissions";
import { ExplainerText } from "@shared/ui";
import { useInvalidateAfterTableMutation, useUnitOptions } from "@hooks/index";
import {
  useShareArticleColumn,
  useShareTypeVariationColumns,
  variationColumnKey,
} from "@features/commissioning/hooks";
import { notify, toApiDate } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

/**
 * Pivot view for ``DefaultShareArticleInShare``.
 *
 * Rows are share articles (filtered to those associated with any share type
 * via their ``share_option`` fields). Columns are share-type variations
 * grouped by their share type, rendered via `useShareTypeVariationColumns`
 * (also used by `DeliveryStationsDetails`). Each cell holds the default
 * quantity; clearing it (or 0) deletes the underlying row. Saving a row
 * sends one `bulk_upsert` with the cells that changed.
 */

/** A default quantity as the bulk upsert takes it: a positive number as text,
 *  or null for none — a blank cell and 0 both mean none. */
function quantityOf(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? String(parsed) : null;
}

/** Share-article rows as returned by the API with `is_data_list=true`. */
interface ShareArticleListRow {
  id: string;
  name: string;
  default_movement_unit: string;
  share_option: string | null;
  share_option2: string | null;
  share_option3: string | null;
}

export default function DefaultShareArticlesInShare() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isOffice } = useRoles();
  const { unitOptions } = useUnitOptions();

  // --- Shared column hooks ------------------------------------------------

  // The shared `useShareArticleColumn` fetches the article list AND builds
  // the SELECT column. Here the row IS the article, so we force the cell
  // disabled and drop the unit-change handler that the hook normally wires.
  const {
    shareArticleColumn,
    shareArticles,
    isLoading: shareArticleColumnLoading,
  } = useShareArticleColumn({
    filters: { is_data_list: true, is_active: true } as Record<string, unknown>,
    // No autofillContext on purpose: the row IS the article in this view;
    // we don't want any autofill side effects on selection.
    disableCondition: () => true,
    overrides: {
      fixed: "left",
      width: "16em",
      required: false,
    },
  });

  const today = useMemo(() => toApiDate(dayjs())!, []);
  const {
    variationColumns,
    variations,
    loading: variationColumnsLoading,
  } = useShareTypeVariationColumns({
    // Only PHYSICAL variations get content planning here — virtual variations
    // resolve into their physical components and carry no content of their own.
    filters: { active_at_date: today, physical: true } as Record<string, unknown>,
    inputType: "positive_decimal2",
    width: "5em",
  });

  // --- Default-share rows -------------------------------------------------

  const defaultsQueryKey = useMemo(
    () => getCommissioningDefaultShareArticlesInShareListQueryKey(),
    [],
  );
  const {
    data: defaultsRaw,
    isFetching: defaultsFetching,
    isSuccess: defaultsLoaded,
    isError: defaultsFailed,
    refetch: refetchDefaults,
  } = useCommissioningDefaultShareArticlesInShareList();

  // Read-only until the stored amounts are in: without them every cell looks
  // empty, and a save would clear what is stored.
  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice && defaultsLoaded),
    [isOffice, defaultsLoaded],
  );

  // --- Pivot --------------------------------------------------------------

  const filteredShareArticles = useMemo<ShareArticleListRow[]>(() => {
    const list = shareArticles as unknown as ShareArticleListRow[];
    return list.filter(
      (sa) => sa.share_option || sa.share_option2 || sa.share_option3,
    );
  }, [shareArticles]);

  // Index existing defaults by (share_article, variation) — pivot is O(N).
  const defaultsIndex = useMemo(() => {
    const map = new Map<string, DefaultShareArticleInShare>();
    for (const d of (defaultsRaw ?? []) as DefaultShareArticleInShare[]) {
      map.set(`${d.share_article}:${d.share_type_variation}`, d);
    }
    return map;
  }, [defaultsRaw]);

  const pivotedRows = useMemo<TableRecord[]>(() => {
    return filteredShareArticles.map((sa) => {
      const row: TableRecord = {
        key: sa.id,
        id: sa.id,
        // Keys consumed by useShareArticleColumn (dataIndex `share_article_name`
        // with FK `share_article`).
        share_article: sa.id,
        share_article_name: sa.name,
        default_movement_unit: sa.default_movement_unit,
      };
      for (const v of variations) {
        if (!v.id) continue;
        const existing = defaultsIndex.get(`${sa.id}:${v.id}`);
        row[variationColumnKey(v.id)] = existing ? existing.quantity : null;
      }
      return row;
    });
  }, [filteredShareArticles, variations, defaultsIndex]);

  const bulkUpsert = useMutation({
    mutationFn: (payload: DefaultShareArticleInShareBulkUpsertRequest) =>
      commissioningDefaultShareArticlesInShareBulkUpsertCreate(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: defaultsQueryKey });
    },
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: defaultsQueryKey });
  }, [queryClient, defaultsQueryKey]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidate);

  const apiFunctions = useMemo<ApiFunctions>(
    () => ({
      // No ``list``: the page owns the data (``pivotedRows`` →
      // ``initialData``). A local ``list`` returning the captured rows would
      // make EditableTable double-fetch (auto-fetch fires when
      // ``showSearchBar`` + ``apiFunctions.list`` are both set) against a
      // stale closure. Search still works client-side over ``initialData``.
      update: async (id, data) => {
        // Only the cells that differ from what is stored: a cell the office
        // didn't touch must not overwrite, or clear, an amount on the server.
        const entries: DefaultShareArticleInShareBulkEntry[] = [];
        for (const v of variations) {
          if (!v.id || !(variationColumnKey(v.id) in data)) continue;
          const quantity = quantityOf(data[variationColumnKey(v.id)]);
          const stored = defaultsIndex.get(`${id}:${v.id}`)?.quantity;
          if (quantity !== quantityOf(stored)) {
            entries.push({ share_type_variation: v.id, quantity });
          }
        }
        let stored = [...defaultsIndex.values()].filter(
          (d) => d.share_article === id,
        );
        if (entries.length > 0) {
          try {
            stored = await bulkUpsert.mutateAsync({ share_article: id, entries });
          } catch (err) {
            notify.error(
              getErrorMessage(
                err,
                t("commissioning.default_share_articles_save_failed"),
              ),
            );
            throw err;
          }
        }
        // The row as stored, so a cell saved as 0 or left blank shows empty.
        const row: Record<string, unknown> = { ...data };
        for (const v of variations) {
          if (!v.id) continue;
          row[variationColumnKey(v.id)] =
            stored.find((d) => d.share_type_variation === v.id)?.quantity ??
            null;
        }
        return { data: row };
      },
    }),
    [variations, bulkUpsert, defaultsIndex, t],
  );

  // --- Columns -----------------------------------------------------------

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(() => {
    const unitColumn: EditableColumnConfig<TableRecord> = {
      title: <>{t("commissioning.default_movement_unit")}</>,
      dataIndex: "default_movement_unit",
      key: "default_movement_unit",
      inputType: "select",
      required: false,
      align: "center",
      fixed: "left",
      width: "6em",
      options: unitOptions,
      readOnly: true,
      disabled: true,
      render: (value) => {
        const opt = unitOptions.find(
          (o: { value: string; label: string }) => o.value === value,
        );
        return opt ? opt.label : (value as string);
      },
    };

    return [
      shareArticleColumn as EditableColumnConfig<TableRecord>,
      unitColumn,
      ...variationColumns,
    ];
  }, [shareArticleColumn, variationColumns, unitOptions, t]);

  return (
    <div>
      <div>
        <h1 className="mb-0">
          {t("commissioning.default_share_articles_in_share")}
        </h1>
      </div>

      {defaultsFailed && (
        <Alert
          type="error"
          showIcon
          message={t("table.load_failed_title")}
          description={t("table.load_failed_hint")}
          action={
            <Button size="small" onClick={() => refetchDefaults()}>
              {t("table.retry")}
            </Button>
          }
          className="editable-table-banner"
        />
      )}

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        initialData={pivotedRows}
        loading={
          defaultsFetching ||
          shareArticleColumnLoading ||
          variationColumnsLoading ||
          bulkUpsert.isPending
        }
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
        className="custom-jasmin-table w-max"
        focusIndex="share_article_name"
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.default_share_articles_in_share")}
      </ExplainerText>
    </div>
  );
}
