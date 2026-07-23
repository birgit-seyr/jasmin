import { AddShareArticleEntry } from "@features/commissioning/components";
import {
  useAmountUnitSizeColumns,
  useSellerColumn,
  useShareArticleColumn,
  useShareArticles,
  useShareTypeVariations,
  variationAmountKey,
} from "@features/commissioning/hooks";
import {
  getShareTypeVariationSizeLabelPure,
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useNumberFormat,
  useUnitOptions,
} from "@hooks/index";
import {
  commissioningDefaultShareContentsBulkCreateCreate,
  commissioningDefaultShareContentsBulkDeleteDestroy,
  commissioningDefaultShareContentsBulkUpdatePartialUpdate,
  getCommissioningDefaultShareContentsBulkListListQueryKey,
  useCommissioningDefaultShareContentsBulkListList,
  useCommissioningDefaultShareContentsSubscriberCountsRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDefaultShareContentsBulkListListParams,
  CommissioningDefaultShareContentsSubscriberCountsRetrieveParams,
  DefaultShareContentRequest,
} from "@shared/api/generated/models";
import { ShareTypeEnum } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { YearSelector } from "@shared/selectors";
import { EditableTable, gatedByPermission } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable";
import { ExplainerText } from "@shared/ui";
import { activeAtDateForWeek, isYearInPast } from "@shared/utils";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Space } from "antd";
import type { FormInstance } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  countDeliveryWeeks,
  suggestPerShareAmounts,
  type VariationWeightCount,
} from "../utils/planningWeightSplit";

const currentYear = dayjs().year();

/** Long-term planning input direction: enter the per-share amount and read the
 *  total (``per_share``, the classic view), or enter a target total + weeks and
 *  get a suggested per-share split (``total``, the reverse view). */
type PlanningMode = "per_share" | "total";

interface PlanningLongTermHarvestSharesBaseProps {
  shareOption: ShareTypeEnum;
  // Boolean article-list flags (e.g. ``is_active``, ``get_price_info``). Was
  // typed ``string`` but every caller passes booleans; aligned with
  // ``PlanningHarvestSharesBase`` so both can share a dispatcher.
  shareArticleFilters: Record<string, boolean>;
  pageTitle: string;
  explainerKey: string;
  /** Title the article column generically ("Artikel") instead of
   *  "Gemüse / Obst" — used by the additional-share planners (honey, etc.),
   *  where the harvest framing doesn't fit. */
  genericArticleColumn?: boolean;
  /** Whether the "Gesamtmenge" reverse-input mode (target total → suggested
   *  per-share split) is offered. Only share types that plan complexly
   *  (``needs_complex_planning``) get the toggle; simple ones show the classic
   *  per-share view only. Defaults to off. */
  allowTotalMode?: boolean;
}

export default function PlanningLongTermHarvestSharesBase({
  shareOption,
  shareArticleFilters,
  pageTitle,
  explainerKey,
  genericArticleColumn = false,
  allowTotalMode = false,
}: PlanningLongTermHarvestSharesBaseProps) {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [mode, setMode] = useState<PlanningMode>("per_share");
  // The toggle can be hidden (simple share types); force per-share then, so a
  // stale "total" can never leak the reverse columns when it's not offered.
  const effectiveMode: PlanningMode = allowTotalMode ? mode : "per_share";
  const isPast = useMemo(() => isYearInPast(selectedYear), [selectedYear]);
  const queryClient = useQueryClient();

  const { t } = useTranslation();
  const { format } = useNumberFormat();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => gatedByPermission(!isPast && isOffice),
    [isPast, isOffice],
  );
  const { getUnitLabel } = useUnitOptions();

  const { shareArticleColumn, handleUnitChange } = useShareArticleColumn({
    // Restrict selectable articles to those assigned to this share option.
    filters: { ...shareArticleFilters, share_option: shareOption },
    showFruitsAndVegs: !genericArticleColumn,
    tooltip: false,
    // Seed only the unit on article select — no crate / amount_per_pu, which
    // would otherwise leak into the default-content payload (the backend reads
    // every ``amount_*`` key as a share_type_variation id).
    articleDefaults: "longtermplanning",
  });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
    overrides: {
      unit: { onFieldChange: handleUnitChange },
    },
  });

  const { shareArticles, refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);
  const { noteColumn } = useNoteColumn();
  // The seller only applies to purchased articles, so the column is editable
  // only when the row's currently-selected share_article is_purchased.
  const purchasedArticleIds = useMemo(
    () =>
      new Set(
        shareArticles
          .filter((article) => article.is_purchased)
          .map((article) => String(article.value)),
      ),
    [shareArticles],
  );
  const sellerColumnOverrides = useMemo(
    () => ({
      disabled: (record: TableRecord) =>
        !purchasedArticleIds.has(String(record.share_article)),
    }),
    [purchasedArticleIds],
  );
  const sellerColumn = useSellerColumn({
    overrides: sellerColumnOverrides,
  });

  const listParams = useMemo(
    (): CommissioningDefaultShareContentsBulkListListParams => ({
      year: selectedYear,
      share_option: shareOption,
    }),
    [selectedYear, shareOption],
  );

  const { data: rawData, isFetching } =
    useCommissioningDefaultShareContentsBulkListList(listParams);
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey:
        getCommissioningDefaultShareContentsBulkListListQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  // Stop reorder-on-save — see ``useInvalidateAfterTableMutation``.
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      // ``_target_total`` is a UI-only field driving the "Gesamtmenge" mode's
      // suggestion — never persisted. The backend keys amounts by variation id
      // (``amount_<id>``), so strip it from the payload rather than let it ride
      // along. (The resulting total is derived for display only, not stored.)
      const { _target_total, ...rest } = transformedData;
      void _target_total;

      return {
        ...rest,
        year: selectedYear,
        share_option: shareOption,
      };
    },
    [selectedYear, shareOption],
  );

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    if (record.key === -1) {
      const defaultValues = {
        size: "M",
        note: "",
        only_odd_weeks: false,
        only_even_weeks: false,
        only_every_three_weeks: false,
      };

      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues };
    }

    return record;
  }, []);

  const shareTypeVariationFilters = useMemo(() => {
    return {
      physical: true,
      active_at_date: activeAtDateForWeek(selectedYear, 50),
      share_option: shareOption,
    };
  }, [selectedYear, shareOption]);

  const { shareTypeVariations } = useShareTypeVariations(
    shareTypeVariationFilters,
  );

  // Reverse ("Gesamtmenge") mode only: the per-variation active-subscriber
  // snapshot the forward ``needed_amount`` uses, fetched once so the split can
  // run entirely client-side. Skipped in the forward view.
  const { data: subscriberCounts } =
    useCommissioningDefaultShareContentsSubscriberCountsRetrieve(
      {
        year: selectedYear,
        share_option: shareOption,
      } as CommissioningDefaultShareContentsSubscriberCountsRetrieveParams,
      { query: { enabled: effectiveMode === "total" } },
    );

  // ``average_weight`` (per size) + subscriber count (per size) — the two
  // inputs the weight-split needs. Weight rides along on every variation; the
  // count comes from the snapshot endpoint above.
  const variationWeightCounts = useMemo<VariationWeightCount[]>(
    () =>
      shareTypeVariations.map((variation) => ({
        variationId: String(variation.id),
        averageWeight:
          variation.average_weight != null
            ? Number(variation.average_weight)
            : null,
        subscriberCount: Number(subscriberCounts?.[String(variation.id)] ?? 0),
      })),
    [shareTypeVariations, subscriberCounts],
  );

  // Given the currently-edited row's target total + week range + parity, seed
  // the per-share amount cells with the weight-split suggestion and the live
  // "≈ tatsächlich" preview. The office can still tweak any cell before saving.
  const recomputeSuggestion = useCallback(
    (form: FormInstance) => {
      const values = form.getFieldsValue(true) as Record<string, unknown>;
      const weeks = countDeliveryWeeks(
        values.range_1 as number,
        values.range_2 as number,
        {
          onlyOdd: Boolean(values.only_odd_weeks),
          onlyEven: Boolean(values.only_even_weeks),
          onlyEveryThree: Boolean(values.only_every_three_weeks),
        },
      );
      const unit = values.unit as string;
      // Piece-based units can't deliver a fractional share — floor to whole.
      const floorStep = unit === "PCS" || unit === "BUNCH" ? 1 : 0.1;
      const result = suggestPerShareAmounts(
        Number(values._target_total),
        weeks,
        variationWeightCounts,
        { floorStep },
      );

      // Fill the per-share amount cells with the suggestion. The "≈ tatsächlich"
      // total is derived live in the needed_amount column's render from these
      // (registered) fields — not stored here — so it also reflects manual
      // tweaks and survives ``Form.useWatch`` (which only sees registered
      // fields, so an ad-hoc ``_actual_total`` would never propagate).
      const patch: Record<string, unknown> = {};
      for (const variation of variationWeightCounts) {
        if (variation.variationId in result.amountsByVariation) {
          patch[variationAmountKey(variation.variationId)] =
            result.amountsByVariation[variation.variationId];
        }
      }
      form.setFieldsValue(patch);
    },
    [variationWeightCounts],
  );

  const shareTypeVariationColumns: EditableColumnConfig<TableRecord>[] =
    useMemo(() => {
      return shareTypeVariations.map(
        (variation): EditableColumnConfig<TableRecord> => ({
          title: getShareTypeVariationSizeLabelPure(variation.size, t),
          // dataIndex AND key must be the SAME wire field. The default-share
          // backend keys amounts by variation id as `amount_<id>` (there is no
          // day axis here); previously `key` said `variation_<id>` while
          // `dataIndex` said `amount_<id>` — a latent footgun. See
          // docs/day-variation-columns-audit.md (Phase 4).
          dataIndex: variationAmountKey(variation.id!),
          inputType: "positive_decimal2",
          key: variationAmountKey(variation.id!),
          align: "center",
          width: "5em",
          className: "column-group-start",

          render: (value: unknown, record: TableRecord) => {
            if (value === null || value === undefined || value === "")
              return "";

            const numValue = parseFloat(String(value));
            if (isNaN(numValue)) return String(value);

            const unit = record.unit as string;
            const decimals = unit === "PCS" || unit === "BUNCH" ? 0 : 3;

            return format(numValue, decimals);
          },
        }),
      );
    }, [shareTypeVariations, t, format]);

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
      },
      ...amountUnitSizeColumns,

      ...(effectiveMode === "total"
        ? ([
            {
              title: <>{t("commissioning.planning_long_term.target_total")}</>,
              dataIndex: "_target_total",
              key: "_target_total",
              inputType: "positive_decimal2",
              align: "center",
              width: "9em",
              className: "column-group-start",
              // Re-run the weight-split whenever the target total is edited.
              onFieldChange: (
                _value: unknown,
                _record: TableRecord,
                form: FormInstance,
              ) => {
                recomputeSuggestion(form);
                return undefined;
              },
            },
          ] as EditableColumnConfig<TableRecord>[])
        : []),
      {
        title: <>{t("commissioning.KW")}</>,
        dataIndex: "kw",
        key: "kw",
        width: "8em",
        className: "column-group-start",
        children: [
          {
            title: <>{t("commissioning.from")}</>,
            dataIndex: "range_1",
            key: "range_1",
            inputType: "kw",
            required: true,
            align: "center",
            className: "column-group-start",

            width: "4.5em",
            onFieldChange:
              effectiveMode === "total"
                ? (
                    _value: unknown,
                    _record: TableRecord,
                    form: FormInstance,
                  ) => {
                    recomputeSuggestion(form);
                    return undefined;
                  }
                : undefined,
          },
          {
            title: <>{t("commissioning.until")}</>,
            dataIndex: "range_2",
            key: "range_2",
            inputType: "kw",
            required: true,
            align: "center",
            width: "4.5em",
            onFieldChange:
              effectiveMode === "total"
                ? (
                    _value: unknown,
                    _record: TableRecord,
                    form: FormInstance,
                  ) => {
                    recomputeSuggestion(form);
                    return undefined;
                  }
                : undefined,
          },
        ],
      },
      {
        title: <>{t("commissioning.only_odd_weeks")}</>,
        dataIndex: "only_odd_weeks",
        key: "only_odd_weeks",
        inputType: "checkbox",
        required: false,
        align: "center",
        onFieldChange: (
          checked: unknown,
          _record: TableRecord,
          form: FormInstance,
        ) => {
          if (checked) {
            form.setFieldsValue({
              only_even_weeks: false,
              only_every_three_weeks: false,
            });
          }
          if (effectiveMode === "total") recomputeSuggestion(form);
          return undefined;
        },
      },
      {
        title: <>{t("commissioning.only_even_weeks")}</>,
        dataIndex: "only_even_weeks",
        key: "only_even_weeks",
        inputType: "checkbox",
        required: false,
        align: "center",
        onFieldChange: (
          checked: unknown,
          _record: TableRecord,
          form: FormInstance,
        ) => {
          if (checked) {
            form.setFieldsValue({
              only_odd_weeks: false,
              only_every_three_weeks: false,
            });
          }
          if (effectiveMode === "total") recomputeSuggestion(form);
          return undefined;
        },
      },
      {
        title: <>{t("commissioning.only_every_three_weeks")}</>,
        dataIndex: "only_every_three_weeks",
        key: "only_every_three_weeks",
        inputType: "checkbox",
        required: false,
        align: "center",
        onFieldChange: (
          checked: unknown,
          _record: TableRecord,
          form: FormInstance,
        ) => {
          if (checked) {
            form.setFieldsValue({
              only_odd_weeks: false,
              only_even_weeks: false,
            });
          }
          if (effectiveMode === "total") recomputeSuggestion(form);
          return undefined;
        },
      },
      {
        title: <>{t("commissioning.amount")}</>,
        dataIndex: "_amount_group",
        key: "amount",
        width: "8em",
        className: "column-group-start",

        children: [...shareTypeVariationColumns],
      },

      {
        // In "total" mode this shows the LIVE result of the suggestion
        // (``_actual_total``, updated as the office types the target total) —
        // always ≤ the target because the split floors. For a saved row / the
        // classic view it shows the backend-computed ``needed_amount``.
        title: (
          <>
            {t(
              effectiveMode === "total"
                ? "commissioning.planning_long_term.actual_total"
                : "commissioning.needed_amount",
            )}
          </>
        ),
        dataIndex: "needed_amount",
        key: "needed_amount",
        inputType: "positive_integer",
        className: "column-group-start",

        required: false,
        disabled: true,
        readOnly: true,
        align: "center",
        width: "10em",
        render: (_, record) => {
          const rec = record as Record<string, unknown>;
          // While a row is edited in total mode (it carries the UI-only
          // ``_target_total``), compute the resulting total LIVE from the
          // current per-share amounts × subscribers × weeks — so it reflects
          // the suggestion AND any manual tweak. Otherwise show the
          // backend-computed ``needed_amount``.
          const isEditingTotal =
            effectiveMode === "total" &&
            rec._target_total != null &&
            rec._target_total !== "";
          if (isEditingTotal) {
            const weeks = countDeliveryWeeks(
              rec.range_1 as number,
              rec.range_2 as number,
              {
                onlyOdd: Boolean(rec.only_odd_weeks),
                onlyEven: Boolean(rec.only_even_weeks),
                onlyEveryThree: Boolean(rec.only_every_three_weeks),
              },
            );
            let total = 0;
            for (const variation of variationWeightCounts) {
              const amount = Number(
                rec[variationAmountKey(variation.variationId)] ?? 0,
              );
              if (Number.isFinite(amount)) {
                total += variation.subscriberCount * amount * weeks;
              }
            }
            if (total <= 0) return "";
            return (
              <>
                {format(total, 0)} {getUnitLabel(record.unit as string)}
              </>
            );
          }
          const value = Number(record.needed_amount);
          if (!Number.isFinite(value)) return "";
          return (
            <>
              {format(value, 0)} {getUnitLabel(record.unit as string)}
            </>
          );
        },
      },
      sellerColumn,

      {
        title: "",
        dataIndex: "timeline",
        key: "timeline",
        align: "center",
        width: "40em",
        disabled: true,
        readOnly: true,
        render: (_: unknown, record: TableRecord) => {
          if (!record.range_1 || !record.range_2) return null;

          const startWeek = parseInt(String(record.range_1));
          const endWeek = parseInt(String(record.range_2));

          if (isNaN(startWeek) || isNaN(endWeek)) return null;

          // Calculate which weeks will actually have deliveries
          const actualWeeks = [];
          for (let week = startWeek; week <= endWeek; week++) {
            let include = true;

            if (record.only_odd_weeks && week % 2 === 0) {
              include = false;
            }
            if (record.only_even_weeks && week % 2 !== 0) {
              include = false;
            }
            if (record.only_every_three_weeks) {
              const position = week - startWeek;
              if (position % 3 !== 0) {
                include = false;
              }
            }

            if (include) {
              actualWeeks.push(week);
            }
          }

          const weekWidth = 10;
          const padding = 4;

          return (
            <div
              style={{
                position: "relative",
                height: "10px",
                backgroundColor: "var(--color-bg-hover)",
                border: "1px solid var(--color-border)",
                borderRadius: "2px",
                margin: "0 auto",
              }}
            >
              {actualWeeks.map((week) => {
                const position = (week - 1) * weekWidth + padding / 2;
                return (
                  <div
                    key={week}
                    style={{
                      position: "absolute",
                      left: `${position}px`,
                      width: `${weekWidth}px`,
                      height: "8px",
                      top: "1px",
                      backgroundColor: "var(--color-success)",
                      borderRadius: "1px",
                    }}
                  />
                );
              })}
            </div>
          );
        },
      },
      {
        ...noteColumn,
        align: "center",
        width: "25em",
      },
    ],
    [
      shareArticleColumn,
      amountUnitSizeColumns,
      shareTypeVariationColumns,
      sellerColumn,
      noteColumn,
      t,
      format,
      getUnitLabel,
      effectiveMode,
      recomputeSuggestion,
      variationWeightCounts,
    ],
  );

  const apiFunctions: ApiFunctions = useMemo(
    () => ({
      create: (data) =>
        commissioningDefaultShareContentsBulkCreateCreate(
          data as unknown as DefaultShareContentRequest,
        ).then((res) => ({ data: res as unknown as TableRecord })),
      update: (id, data) =>
        commissioningDefaultShareContentsBulkUpdatePartialUpdate(
          id,
          data as unknown as DefaultShareContentRequest,
        ).then((res) => ({ data: res as unknown as TableRecord })),
      delete: (id) => commissioningDefaultShareContentsBulkDeleteDestroy(id),
    }),
    [],
  );

  return (
    <div>
      <h1>{pageTitle}</h1>
      <YearSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
      />
      <div style={{ marginTop: "2em" }}>
        {allowTotalMode && (
          <Space.Compact
            aria-label={t("commissioning.planning_long_term.mode_label")}
          >
            <Button
              type={mode === "per_share" ? "primary" : "default"}
              aria-pressed={mode === "per_share"}
              onClick={() => setMode("per_share")}
            >
              {t("commissioning.planning_long_term.mode_per_share")}
            </Button>
            <Button
              type={mode === "total" ? "primary" : "default"}
              aria-pressed={mode === "total"}
              onClick={() => setMode("total")}
            >
              {t("commissioning.planning_long_term.mode_total")}
            </Button>
          </Space.Compact>
        )}
      </div>

      <EditableTable
        key={`${selectedYear}-${effectiveMode}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={data}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        uniqueCheck={["share_article", "unit", "size"]}
        uniqueCheckMessage={t(
          "validation.unique.share_article_unit_size_must_be_unique",
        )}
        permissions={permissions}
      />

      <AddShareArticleEntry
        disabled={isPast}
        defaultValues={{ is_purchased: true }}
        onSuccess={() => refetchShareArticles()}
      />

      <ExplainerText title={t("common.info")}>{t(explainerKey)}</ExplainerText>
    </div>
  );
}
