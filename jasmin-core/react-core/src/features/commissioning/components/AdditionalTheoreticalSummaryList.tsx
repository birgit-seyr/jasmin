/**
 * Shared page body for the Washing and Cleaning lists. The two are the
 * same documentation-summary page end-to-end — same summary endpoint
 * (``model: "washamount" | "cleanamount"``), same processed-data math,
 * same add-additional-amount mutation endpoints, same columns, toggles and
 * mobile/PDF wiring. Only the ``model``, the i18n labels, the PDF/mobile
 * components, and the edit-permission scope differ; those are config props.
 *
 * WashingList.tsx and CleaningList.tsx are thin shells that render this
 * with their own config. The data/state/invalidate boilerplate lives in
 * ``useDocumentationSummaryPage``.
 */

import { AppstoreOutlined, UnorderedListOutlined } from "@ant-design/icons";
import type { FormInstance } from "antd";
import { Button, Space } from "antd";
import dayjs from "dayjs";
import type { TFunction } from "i18next";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate,
  commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreateBody,
  CommissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdateBody,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  ExplainerText,
  MobileStack,
  PastWarningMessage,
  ToolTipIcon,
} from "@shared/ui";
import {
  useIsMobile,
  useNoteColumn,
  useNumberFormat,
  useSizeOptions,
  useUnitOptions,
} from "@hooks/index";
import {
  useAmountUnitSizeColumns,
  useDocumentationSummaryPage,
  useShareArticleColumn,
} from "@features/commissioning/hooks";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
} from "@shared/utils";

const currentWeek = dayjs().isoWeek();

const widthShareArticle = "35%";
const widthTotalAmountText = "30%";
const widthNote = "35%";

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
  is_purchased: false,
};

export interface AdditionalTheoreticalSummaryListConfig {
  /** ``washamount`` or ``cleanamount`` — drives the field names + endpoints. */
  model: "washamount" | "cleanamount";
  /**
   * Whether the caller may add/edit rows. Computed by each shell from its
   * OWN role hook — washing is office-only, cleaning is gardener/staff/
   * office/admin. (Pre-existing drift, deliberately preserved per-page.)
   */
  canEdit: boolean;
  titleKey: string;
  daySuffixKey: string;
  teamViewLabelKey: string;
  explainerKey: string;
  theoreticalColumnTitleKey: string;
  toProcessColumnTitleKey: string;
  additionalColumnTitleKey: string;
  additionalTooltipKey: string;
  amountColumnTitleKey: string;
  /**
   * dataIndex for the computed total-amount text column. The page-specific
   * PDF reads this exact key (``computed_total_wash_amount_text`` /
   * ``computed_total_clean_amount_text``), so it stays configurable.
   */
  totalAmountTextField: string;
  /** Render the page-specific PDF download button. */
  renderPdf: (
    data: TableRecord[] | null,
    ctx: {
      year: number;
      week: number;
      dayName: string;
      filename: string;
      t: TFunction;
    },
  ) => ReactNode;
  /** Optional mobile card (washing has one; cleaning doesn't). */
  renderMobileCard?: (
    record: TableRecord,
    onEdit: (r: TableRecord) => void,
  ) => ReactNode;
}

export default function AdditionalTheoreticalSummaryList(
  config: AdditionalTheoreticalSummaryListConfig,
) {
  const {
    model,
    canEdit,
    titleKey,
    daySuffixKey,
    teamViewLabelKey,
    explainerKey,
    theoreticalColumnTitleKey,
    toProcessColumnTitleKey,
    additionalColumnTitleKey,
    additionalTooltipKey,
    amountColumnTitleKey,
    totalAmountTextField,
    renderPdf,
    renderMobileCard,
  } = config;

  const theoreticalField = `theoretical_${model}_amount`;
  const additionalField = `additional_theoretical_${model}_amount`;

  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const [isGardenerView, setIsGardenerView] = useState(false);

  useEffect(() => {
    if (isMobile) setIsGardenerView(true);
  }, [isMobile]);

  const {
    selectedYear,
    setSelectedYear,
    selectedWeek,
    setSelectedWeek,
    selectedDay,
    setSelectedDay,
    isPast,
    rows,
    isFetching,
    invalidateData,
    onDeleteSuccess,
    customSaveBase,
    tableKey,
  } = useDocumentationSummaryPage({ model });

  // The summary list and the add/update endpoints return DIFFERENT row
  // shapes (summary = joined Theoretical + Additional + Actual; create =
  // bare AdditionalTheoretical*). The optimistic-add path can't reconcile
  // that — the saved row's id doesn't match any summary-row id — so on
  // save we just invalidate and let the list refetch in the summary shape.
  const onSaveSuccess = invalidateData;

  const { shareArticleColumn } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "harvest",
  });
  const { getUnitLabel } = useUnitOptions();
  const { getSizeLabel } = useSizeOptions();
  const { format } = useNumberFormat();
  const { noteColumn } = useNoteColumn();
  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
    overrides: {
      unit: {
        disabled: (record: Record<string, unknown>) => {
          if (record.key != -1) return true;
        },
        hidden: isMobile || isGardenerView,
      },
      size: {
        disabled: (record: Record<string, unknown>) => {
          if (record.key != -1) return true;
        },
        hidden: isMobile || isGardenerView,
      },
    },
  });

  const data = useMemo(
    () =>
      rows.filter((item) => {
        const theoreticalAmount = item[theoreticalField] as number | null;
        const additionalAmount = item[additionalField] as number | null;
        const actualAmount = item.amount as number | null;
        return !!(theoreticalAmount || additionalAmount || actualAmount);
      }) as unknown as TableRecord[],
    [rows, theoreticalField, additionalField],
  );

  const processedData = useMemo(() => {
    return data.map((record) => {
      const theoretical = parseNumber(record[theoreticalField]);
      const inStock = parseNumber(record.theoretical_current_stock);
      const additional = parseNumber(record[additionalField]);

      const stillInStockAmount = Math.max(inStock, 0);
      const toProcessAmount = Math.max(theoretical - stillInStockAmount, 0);
      const totalAmount = Math.max(toProcessAmount + additional, 0);

      const totalAmountText = totalAmount
        ? `${format(totalAmount, 0)} ${getUnitLabel(record.unit as string)}`
        : "";

      const sizeLabel =
        record.size && record.size !== "M"
          ? ` (${getSizeLabel(record.size as string)})`
          : "";
      const articleWithSize = `${record.share_article_name}${sizeLabel}`;

      return {
        ...record,
        computed_still_in_stock: stillInStockAmount,
        computed_to_process: toProcessAmount,
        computed_article_with_size: articleWithSize,
        [totalAmountTextField]: totalAmountText,
        computed_unit_label: getUnitLabel(record.unit as string),
      } as TableRecord;
    });
  }, [
    data,
    theoreticalField,
    additionalField,
    totalAmountTextField,
    getUnitLabel,
    getSizeLabel,
    format,
  ]);

  const customSave = useMemo(
    () => (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      ...customSaveBase,
    }),
    [customSaveBase],
  );

  const customEdit = useMemo(
    () => (record: TableRecord, form: FormInstance) => {
      if (record.key === -1) {
        const defaultValues = { size: "M" };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues } as TableRecord;
      }
      const updatedRecord = { ...record, amount: record[additionalField] };
      form.setFieldsValue(updatedRecord);
      return updatedRecord as TableRecord;
    },
    [additionalField],
  );

  const columns: EditableColumnConfig<TableRecord>[] = useMemo(
    () => [
      {
        ...shareArticleColumn,
        disabled: (record: TableRecord) => record.key != -1,
        pdf: {
          include: true,
          width: widthShareArticle,
          align: "left",
          dataKey: "computed_article_with_size",
          title: t("commissioning.vegetables_and_fruits"),
        },
      },
      ...amountUnitSizeColumns.map((col) => ({
        ...col,
        pdf: { include: false },
      })),
      {
        title: <>{t(theoreticalColumnTitleKey)}</>,
        dataIndex: theoreticalField,
        key: theoreticalField,
        inputType: "text",
        required: false,
        width: "9em",
        align: "center",
        disabled: true,
        hideInModal: true,
        hidden: isMobile || isGardenerView,
        pdf: { include: false },
      },
      {
        title: <>{t("commissioning.still_in_stock")}</>,
        dataIndex: "computed_still_in_stock",
        key: "computed_still_in_stock",
        inputType: "text",
        required: false,
        width: "8em",
        align: "center",
        disabled: true,
        hidden: isMobile || isGardenerView,
        readOnly: true,
        hideInModal: true,
        pdf: { include: false },
      },
      {
        title: <>{t(toProcessColumnTitleKey)}</>,
        dataIndex: "computed_to_process",
        key: "computed_to_process",
        inputType: "text",
        required: false,
        width: "9em",
        align: "center",
        disabled: true,
        hidden: isMobile || isGardenerView,
        readOnly: true,
        pdf: { include: false },
      },
      {
        title: (
          <>
            {t(additionalColumnTitleKey)}
            <ToolTipIcon title={t(additionalTooltipKey)} />
          </>
        ),
        dataIndex: "amount",
        key: "amount",
        inputType: "negative_integer",
        required: false,
        align: "center",
        width: "8em",
        hidden: isMobile || isGardenerView,
        render: (_: unknown, record: TableRecord) => (
          <>{record[additionalField] ? String(record[additionalField]) : ""}</>
        ),
        pdf: { include: false },
      },
      {
        title: <>{t(amountColumnTitleKey)}</>,
        dataIndex: totalAmountTextField,
        key: totalAmountTextField,
        inputType: "text",
        required: false,
        width: "8em",
        align: "center",
        disabled: true,
        readOnly: true,
        pdf: {
          include: true,
          width: widthTotalAmountText,
          align: "center",
          title: t("commissioning.amount"),
        },
      },
      {
        ...noteColumn,
        disabled: isMobile || isGardenerView,
        pdf: {
          include: true,
          width: widthNote,
          align: "left",
          title: t("commissioning.note"),
        },
      },
    ],
    [
      shareArticleColumn,
      amountUnitSizeColumns,
      noteColumn,
      isMobile,
      isGardenerView,
      t,
      theoreticalField,
      additionalField,
      totalAmountTextField,
      theoreticalColumnTitleKey,
      toProcessColumnTitleKey,
      additionalColumnTitleKey,
      additionalTooltipKey,
      amountColumnTitleKey,
    ],
  );

  const generateFilename = useMemo(() => {
    return generatePdfFilename([
      t(titleKey),
      selectedYear,
      formatWeekLabel(selectedWeek, t),
      formatDayLabel(selectedDay, t),
    ]);
  }, [titleKey, selectedYear, selectedWeek, selectedDay, t]);

  // Page owns the data (initialData) — no ``list`` here, so the table
  // never fetches it itself.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<
        CommissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreateBody &
          TableRecord
      >({
        create: (payload) =>
          commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate(
            payload,
          ),
        update: (id, payload) =>
          commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate(
            id,
            payload as unknown as CommissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdateBody,
          ),
      }),
    [],
  );

  // Add is hidden in the gardener/mobile views; add + edit both require a
  // non-past week and edit permission; rows are never deleted here.
  const permissions = useMemo(
    () => ({
      canAdd: !isPast && !isGardenerView && !isMobile && canEdit,
      canEdit: !isPast && !isMobile && canEdit,
      canDelete: false,
    }),
    [isPast, isGardenerView, isMobile, canEdit],
  );

  return (
    <div>
      <h1>{t(titleKey)}</h1>

      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <DaySelector
          selectedDay={selectedDay}
          setSelectedDay={setSelectedDay}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedYear={selectedYear}
          days={[0, 1, 2, 3, 4, 5, 6]}
          suffix={t(daySuffixKey)}
        />
      </MobileStack>
      {!isMobile && (
        <div className="team-view-toggle-row">
          <Space.Compact>
            <Button
              type={isGardenerView ? "default" : "primary"}
              icon={<UnorderedListOutlined />}
              onClick={() => setIsGardenerView(false)}
            >
              {t("commissioning.office_view")}
            </Button>
            <Button
              type={isGardenerView ? "primary" : "default"}
              icon={<AppstoreOutlined />}
              onClick={() => setIsGardenerView(true)}
            >
              {t(teamViewLabelKey)}
            </Button>
          </Space.Compact>
        </div>
      )}
      {!isMobile &&
        renderPdf(processedData.length > 0 ? processedData : null, {
          year: selectedYear,
          week: selectedWeek ?? currentWeek,
          dayName: getDayName(selectedDay, t),
          filename: generateFilename,
          t,
        })}

      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}

      <EditableTable
        key={tableKey}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={processedData}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
        className={
          isGardenerView ? "w-max custom-jasmin-table" : "custom-jasmin-table"
        }
        uniqueCheck={["share_article", "size", "unit"]}
        uniqueCheckMessage={t(
          "validation.unique.share_article_unit_size_must_be_unique",
        )}
        renderMobileCard={renderMobileCard}
      />
      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t(explainerKey)}
        </ExplainerText>
      )}
    </div>
  );
}

function parseNumber(value: unknown): number {
  const num = parseFloat(value as string);
  return isNaN(num) ? 0 : num;
}
