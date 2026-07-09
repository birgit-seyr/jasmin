import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Button, Popconfirm } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkFinalizeCreate,
  commissioningForecastBulkCopyToNextWeekCreate,
  commissioningForecastCreate,
  commissioningForecastDestroy,
  commissioningForecastPartialUpdate,
  getCommissioningForecastListQueryKey,
  useCommissioningForecastList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BulkFinalizeRequest,
  CommissioningForecastListParams,
  Forecast as ForecastModel,
} from "@shared/api/generated/models";
import { ShareTypeEnum } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ForecastMobileCard } from "@features/commissioning/components/mobileCards";
import { WeekSelector } from "@shared/selectors";
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { BulkActionButton, ExplainerText, PastWarningMessage } from '@shared/ui';
import { AddShareArticleEntry } from '@features/commissioning/components';
import { activeAtDateForWeek, isWeekInPast, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { useActiveShareOptions, useInvalidateAfterTableMutation, useIsMobile, useNoteColumn, useShareTypeVariationSizeOptions, useTableRowSelection, useTenant } from '@hooks/index';
import { useAmountUnitSizeColumns, useFinalColumn, useForecastColumns, useOfferGroups, usePlots, useShareArticleColumn, useShareArticles, useShareTypeVariations, variationColumnKey } from '@features/commissioning/hooks';

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
  is_purchased: false,
};

export default function Forecast() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );

  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  const { canEdit } = useRoles();
  const permissions = useMemo(
    () => gatedByPermission(!isPast && canEdit),
    [isPast, canEdit],
  );
  const { getSetting } = useTenant();
  const isMobile = useIsMobile();

  const { activeShareOptions } = useActiveShareOptions();
  const fruit_and_veg_shares_are_separate =
    activeShareOptions.fruit_and_veg_shares_are_separate ?? false;
  const has_markets = getSetting("has_markets", true);
  const sells_to_resellers = getSetting("sells_to_resellers", true);

  const { shareArticles, refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);
  const { plots, countPlots } = usePlots();
  const { offerGroups, offerGroupsCount } = useOfferGroups();

  const shareTypeVariationFilters = useMemo(() => {
    return {
      physical: true,
      active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
      // Forecast is a HARVEST forecast — ALWAYS scope to harvest-share
      // variations. The fruit-share variations are fetched separately
      // (``shareTypeVariationFiltersFruits``) only when the tenant runs fruit
      // and veg as separate shares. Previously the "not separate" case dropped
      // ``share_option`` entirely, so the query returned EVERY share option
      // (egg / chicken / …) once no fruit share was active.
      share_option: ShareTypeEnum.HARVEST_SHARE,
    };
  }, [selectedYear, selectedWeek]);
  const { shareTypeVariations, shareTypeVariationsCount } =
    useShareTypeVariations(shareTypeVariationFilters);

  const shareTypeVariationFiltersFruits = useMemo(() => {
    if (!fruit_and_veg_shares_are_separate) return null;

    return {
      physical: true,
      active_at_date: activeAtDateForWeek(selectedYear, selectedWeek),
      share_option: ShareTypeEnum.HARVEST_SHARE_FRUIT,
    };
  }, [selectedYear, selectedWeek, fruit_and_veg_shares_are_separate]);

  const {
    shareTypeVariations: shareTypeVariationsFruits,
    shareTypeVariationsCount: shareTypeVariationsFruitsCount,
  } = useShareTypeVariations(shareTypeVariationFiltersFruits);

  const { finalColumn } = useFinalColumn();
  const { noteColumn } = useNoteColumn();

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: {
        disabled: (record: Record<string, unknown>) => {
          if (record.key != -1) return true;
        },
      },
      size: {
        disabled: (record: Record<string, unknown>) => {
          if (record.key != -1) return true;
        },
      },
    },
  });

  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    // Restores the auto-fill of ``unit`` from
    // ``share_article.default_movement_unit`` on share-article change.
    // Forecast has no amount_per_pu / crate / description columns, so the
    // other patch fields written by the "harvest" context are ignored by
    // DRF's ``ForecastSerializer`` (unknown keys are silently dropped).
    articleDefaults: "harvest",
  });

  const isResellerDisabled = useCallback(
    (record: Record<string, unknown>) => {
      const article = shareArticles.find(
        (a) => a.value === record.share_article,
      );
      return (
        "is_sold_to_resellers" in (article ?? {}) &&
        (article as { is_sold_to_resellers?: boolean }).is_sold_to_resellers ===
          false
      );
    },
    [shareArticles],
  );

  const isComponentReady = useMemo(() => {
    return !!(
      shareArticleColumn &&
      amountUnitSizeColumns &&
      amountUnitSizeColumns.length > 0 &&
      shareTypeVariations !== undefined &&
      (fruit_and_veg_shares_are_separate
        ? shareTypeVariationsFruits !== undefined
        : true) &&
      offerGroups !== undefined &&
      plots !== undefined
    );
  }, [
    shareArticleColumn,
    amountUnitSizeColumns,
    shareTypeVariations,
    shareTypeVariationsFruits,
    offerGroups,
    plots,
    fruit_and_veg_shares_are_separate,
  ]);

  const {
    selectedRowKeys,
    setSelectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection((record: TableRecord) => record.key === -1 || isPast);

  const listParams = useMemo<CommissioningForecastListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek!,
      is_past: isPast,
    }),
    [selectedYear, selectedWeek, isPast],
  );

  const { data: rawData, isFetching } = useCommissioningForecastList(
    listParams,
    { query: { enabled: isComponentReady } },
  );
  const data = useMemo(
    () =>
      (rawData ?? []).map((item) => ({
        ...item,
        key: (item as unknown as ForecastModel).id ?? "",
      })) as unknown as TableRecord[],
    [rawData],
  );
  const invalidateData = useCallback(() => {
    setSelectedRowKeys([]);
    queryClient.invalidateQueries({
      queryKey: getCommissioningForecastListQueryKey(listParams),
    });
  }, [queryClient, listParams, setSelectedRowKeys]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      return {
        ...transformedData,
        year: selectedYear,
        delivery_week: selectedWeek,
      };
    },
    [selectedYear, selectedWeek],
  );

  const customEdit = useCallback(
    (record: TableRecord, form: FormInstance) => {
      if (record.key === -1) {
        const defaultValues: Record<string, unknown> = {
          size: "M",
          // New rows default to "for all"; tick the per-variation boxes too
          // (when they're shown, i.e. >1 variation) so the grid never shows a
          // ticked master over unticked variations.
          for_all_harvest_shares: true,
          ...(shareTypeVariationsCount > 1 &&
            Object.fromEntries(
              (shareTypeVariations ?? []).map((v) => [
                variationColumnKey(v.id!),
                true,
              ]),
            )),
          ...(fruit_and_veg_shares_are_separate && {
            for_all_harvest_shares_fruit: true,
            ...(shareTypeVariationsFruitsCount > 1 &&
              Object.fromEntries(
                (shareTypeVariationsFruits ?? []).map((v) => [
                  variationColumnKey(v.id!),
                  true,
                ]),
              )),
          }),
        };

        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues } as TableRecord;
      }

      return record;
    },
    [
      fruit_and_veg_shares_are_separate,
      shareTypeVariations,
      shareTypeVariationsCount,
      shareTypeVariationsFruits,
      shareTypeVariationsFruitsCount,
    ],
  );

  // ── "For all" master ⇄ per-variation checkbox sync ──────────────────────
  // ``for_all_harvest_shares`` (and the fruit variant) make the backend link
  // EVERY active variation, UNION-ed with the explicit ``variation_<id>``
  // flags — so the master box and the per-variation boxes must agree, or
  // unticking a variation while "for all" stays on would still save it. Sync is
  // two-way: ticking the master ticks every variation (and unticking it unticks
  // them); unticking any variation unticks the master; re-ticking the last
  // variation re-ticks the master. (``setFieldsValue`` doesn't fire onChange,
  // so these can't loop.)
  const vegVariationKeys = useMemo(
    () => (shareTypeVariations ?? []).map((v) => variationColumnKey(v.id!)),
    [shareTypeVariations],
  );
  const fruitVariationKeys = useMemo(
    () => (shareTypeVariationsFruits ?? []).map((v) => variationColumnKey(v.id!)),
    [shareTypeVariationsFruits],
  );

  const onForAllVegChange = useCallback(
    (value: unknown): Record<string, unknown> =>
      Object.fromEntries(vegVariationKeys.map((key) => [key, value === true])),
    [vegVariationKeys],
  );
  const onForAllFruitChange = useCallback(
    (value: unknown): Record<string, unknown> =>
      Object.fromEntries(fruitVariationKeys.map((key) => [key, value === true])),
    [fruitVariationKeys],
  );
  const onVegVariationChange = useCallback(
    (
      value: unknown,
      _record: TableRecord,
      form: FormInstance,
      dataIndex: string,
    ): Record<string, unknown> | undefined => {
      if (value !== true) return { for_all_harvest_shares: false };
      const allTicked = vegVariationKeys.every((key) =>
        key === dataIndex ? true : form.getFieldValue(key) === true,
      );
      return allTicked ? { for_all_harvest_shares: true } : undefined;
    },
    [vegVariationKeys],
  );
  const onFruitVariationChange = useCallback(
    (
      value: unknown,
      _record: TableRecord,
      form: FormInstance,
      dataIndex: string,
    ): Record<string, unknown> | undefined => {
      if (value !== true) return { for_all_harvest_shares_fruit: false };
      const allTicked = fruitVariationKeys.every((key) =>
        key === dataIndex ? true : form.getFieldValue(key) === true,
      );
      return allTicked ? { for_all_harvest_shares_fruit: true } : undefined;
    },
    [fruitVariationKeys],
  );

  const shareTypeVariationColumns = useMemo(() => {
    return (
      shareTypeVariations?.map((variation) => ({
        title: (
          <>
            {t("commissioning.for_size", {
              size: getShareTypeVariationSizeLabel(variation.size),
            })}
          </>
        ),
        dataIndex: variationColumnKey(variation.id!),
        inputType: "checkbox",
        key: variationColumnKey(variation.id!),
        align: "center",
        onFieldChange: onVegVariationChange,
      })) || []
    );
  }, [shareTypeVariations, t, onVegVariationChange, getShareTypeVariationSizeLabel]);

  const shareTypeVariationFruitsColumns = useMemo(() => {
    return (
      shareTypeVariationsFruits?.map((variation) => ({
        title: (
          <>
            {t("commissioning.for_size", {
              size: getShareTypeVariationSizeLabel(variation.size),
            })}
          </>
        ),
        dataIndex: variationColumnKey(variation.id!),
        inputType: "checkbox",
        key: variationColumnKey(variation.id!),
        align: "center",
        onFieldChange: onFruitVariationChange,
      })) || []
    );
  }, [
    shareTypeVariationsFruits,
    t,
    onFruitVariationChange,
    getShareTypeVariationSizeLabel,
  ]);

  const offerGroupColumns = useMemo(() => {
    return (
      offerGroups?.map((group) => ({
        title: (
          <>
            {t("commissioning.for_offer_group", {
              offer_group_number: group.number,
            })}
          </>
        ),
        dataIndex: `offer_group_${group.id}`,
        inputType: "checkbox",
        key: `offer_group_${group.id}`,
        align: "center",
        disabled: isResellerDisabled,
      })) || []
    );
  }, [offerGroups, isResellerDisabled, t]);

  const columns = useForecastColumns({
    isComponentReady,
    finalColumn,
    shareArticleColumn,
    amountUnitSizeColumns,
    noteColumn,
    fruit_and_veg_shares_are_separate,
    shareTypeVariationsCount,
    shareTypeVariationColumns,
    shareTypeVariationsFruitsCount,
    shareTypeVariationFruitsColumns,
    onForAllVegChange,
    onForAllFruitChange,
    sells_to_resellers: Boolean(sells_to_resellers),
    offerGroupsCount,
    offerGroupColumns,
    isResellerDisabled,
    has_markets: Boolean(has_markets),
    countPlots,
    plots,
  });

  const nextWeekInfo = useMemo(() => {
    const currentDate = dayjs()
      .year(selectedYear)
      .isoWeek(selectedWeek ?? currentWeek);
    const nextWeekDate = currentDate.add(1, "week");
    return {
      week: nextWeekDate.isoWeek(),
      year: nextWeekDate.year(),
    };
  }, [selectedYear, selectedWeek]);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ForecastModel & TableRecord>({
        create: (payload) => commissioningForecastCreate(payload),
        update: (id, payload) =>
          commissioningForecastPartialUpdate(id, payload),
        delete: (id) => commissioningForecastDestroy(id),
      }),
    [],
  );

  if (!isComponentReady) {
    return (
      <div
        className="flex-center"
        style={{
          minHeight: "200px",
        }}
      ></div>
    );
  }

  return (
    <div>
      <h1>{t("commissioning.forecast")}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />
      {!isPast && !isMobile && (
        <div className="bulk-actions-header">
          <strong>{t("commissioning.for_selected")}</strong>
        </div>
      )}

      {!isPast && !isMobile && (
        <div className="button-row-spaced">
          <BulkActionButton
            selectedIds={selectedRowKeys}
            apiFunction={(payload) => {
              const body: BulkFinalizeRequest = {
                model: "forecast",
                app_label: "commissioning",
                ids: payload.ids as string[],
              };
              return commissioningBulkFinalizeCreate(body);
            }}
            buttonText={t("commissioning.finalize")}
            buttonProps={{ type: "primary" }}
            disabled={selectedRowKeys.length === 0}
            onSuccess={invalidateData}
          />
          <Popconfirm
            title={t("commissioning.confirm_forecast_copy_title")}
            description={t("commissioning.confirm_forecast_copy_message", {
              count: selectedRowKeys.length,
              nextWeek: nextWeekInfo.week,
            })}
            icon={null}
            onConfirm={async () => {
              try {
                await commissioningForecastBulkCopyToNextWeekCreate({
                  ids: selectedRowKeys.map(String),
                });
                setSelectedRowKeys([]);
              } catch (error) {
                console.error("Operation failed:", error);
                notify.error(getErrorMessage(error, "Failed to load data"));
              }
            }}
            okText={t("common.yes")}
            cancelText={t("common.cancel")}
            disabled={selectedRowKeys.length === 0}
          >
            <Button
              disabled={selectedRowKeys.length === 0}
              className="selected-rows-action-button"
              type="primary"
            >
              {t("commissioning.copy_selected_to_next_week")}
            </Button>
          </Popconfirm>
        </div>
      )}

      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}

      <EditableTable
        key={`${selectedYear}-${selectedWeek}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={data}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
        uniqueCheck={["share_article", "unit", "size"]}
        uniqueCheckMessage={t("validation.unique.share_article_unit_size_must_be_unique")}
        rowSelection={!isPast && !isMobile ? rowSelectionConfig : undefined}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        loading={isFetching}
        keyboardAddShortcut={true}
        renderMobileCard={(
          record: TableRecord,
          onEdit: (r: TableRecord) => void,
        ) => (
          <ForecastMobileCard
            key={String(record.key)}
            record={record}
            onEdit={onEdit}
          />
        )}
      />
      <AddShareArticleEntry
        disabled={isPast}
        onSuccess={() => refetchShareArticles()}
      />

      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.forecast")}
        </ExplainerText>
      )}
    </div>
  );
}
