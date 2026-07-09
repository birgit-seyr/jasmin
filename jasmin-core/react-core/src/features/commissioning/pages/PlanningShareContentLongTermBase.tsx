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
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDefaultShareContentsBulkListListParams,
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
import type { FormInstance } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const currentYear = dayjs().year();

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
}

export default function PlanningLongTermHarvestSharesBase({
  shareOption,
  shareArticleFilters,
  pageTitle,
  explainerKey,
  genericArticleColumn = false,
}: PlanningLongTermHarvestSharesBaseProps) {
  const [selectedYear, setSelectedYear] = useState(currentYear);
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
      const result = {
        ...transformedData,
        year: selectedYear,
        share_option: shareOption,
      };

      return result;
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

      {
        title: <>{t("commissioning.amount")}</>,
        dataIndex: "_amount_group",
        key: "amount",
        width: "8em",
        children: [...shareTypeVariationColumns],
      },

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
            width: "4.5em",
            className: "column-group-start",
          },
          {
            title: <>{t("commissioning.until")}</>,
            dataIndex: "range_2",
            key: "range_2",
            inputType: "kw",
            required: true,
            align: "center",
            width: "4.5em",
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
          return undefined;
        },
      },

      {
        title: <>{t("commissioning.needed_amount")}</>,
        dataIndex: "needed_amount",
        key: "needed_amount",
        inputType: "positive_integer",
        required: false,
        disabled: true,
        readOnly: true,
        align: "center",
        width: "10em",
        render: (_, record) => (
          <>
            {format(Number(record.needed_amount), 0)}{" "}
            {getUnitLabel(record.unit as string)}
          </>
        ),
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

      <EditableTable
        key={`${selectedYear}`}
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
