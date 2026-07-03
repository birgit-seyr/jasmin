import { useMutation, useQueryClient } from "@tanstack/react-query";
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
import { useInvalidateAfterTableMutation, useUnitOptions } from '@hooks/index';
import { useShareArticleColumn, useShareTypeVariationColumns, variationColumnKey } from '@features/commissioning/hooks';
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

/**
 * Pivot view for ``DefaultShareArticleInShare``.
 *
 * Rows are share articles (filtered to those associated with any share type
 * via their ``share_option`` fields). Columns are share-type variations
 * grouped by their share type, rendered via `useShareTypeVariationColumns`
 * (also used by `DeliveryStationsDetails`). Each cell holds the default
 * quantity; clearing it (or 0) deletes the underlying row. Saving a row
 * sends a single `bulk_upsert` so all variation cells apply atomically.
 */

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
  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice),
    [isOffice],
  );
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
    // No articleDefaults on purpose: the row IS the article in this view;
    // we don't want any autofill side effects on selection.
    disableCondition: () => true,
    overrides: {
      fixed: "left",
      width: "16em",
      required: false,
    },
  });

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const {
    variationColumns,
    variations,
    loading: variationColumnsLoading,
  } = useShareTypeVariationColumns({
    filters: { active_at_date: today } as Record<string, unknown>,
    inputType: "positive_decimal2",
    width: "5em",
  });

  // --- Default-share rows -------------------------------------------------

  const defaultsQueryKey = useMemo(
    () => getCommissioningDefaultShareArticlesInShareListQueryKey(),
    [],
  );
  const { data: defaultsRaw, isFetching: defaultsFetching } =
    useCommissioningDefaultShareArticlesInShareList();

  // --- Pivot --------------------------------------------------------------

  const filteredShareArticles = useMemo<ShareArticleListRow[]>(() => {
    const list = (shareArticles ?? []) as unknown as ShareArticleListRow[];
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
        const entries: DefaultShareArticleInShareBulkEntry[] = [];
        for (const v of variations) {
          if (!v.id) continue;
          const key = variationColumnKey(v.id);
          if (!(key in data)) continue;
          const raw = data[key];
          let quantity: string | null;
          if (raw === null || raw === undefined || raw === "") {
            quantity = null;
          } else {
            const parsed = Number(raw);
            quantity =
              Number.isFinite(parsed) && parsed > 0 ? String(parsed) : null;
          }
          entries.push({ share_type_variation: v.id, quantity });
        }
        try {
          await bulkUpsert.mutateAsync({ share_article: id, entries });
        } catch (err) {
          notify.error(
            getErrorMessage(
              err,
              t("commissioning.default_share_articles_save_failed"),
            ),
          );
          throw err;
        }
        return { data };
      },
    }),
    [variations, bulkUpsert, t],
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
        <h1 style={{ marginBottom: 0 }}>
          {t("commissioning.default_share_articles_in_share")}
        </h1>
      </div>

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
        className="custom-forecast-table w-max"
        focusIndex="share_article_name"
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.default_share_articles_in_share")}
      </ExplainerText>
    </div>
  );
}
