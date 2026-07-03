import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Checkbox, Flex } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate,
  commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate,
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey,
  useCommissioningDocumentationSummarySummaryRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreateBody,
  CommissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdateBody,
  CommissioningDocumentationSummarySummaryRetrieveParams,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ResellerSelector, WeekSelector } from "@shared/selectors";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, PastWarningMessage, ToolTipIcon } from '@shared/ui';
import { AddShareArticleEntry } from '@features/commissioning/components';
// Typed wrapper that internally lazy-imports the PDF template + the
// @react-pdf/renderer library. See PurchaseListPDFGenerator /
// ListPDFGenerator for the click-to-load architecture.
import PurchaseListPDFGenerator from "@features/commissioning/pdfs/exports/PurchaseListPDFGenerator";
import { useInvalidateAfterTableMutation, useIsMobile, useNoteColumn, useNumberFormat, useSizeOptions, useUnitOptions } from '@hooks/index';
import { useAmountUnitSizeColumns, useSellers, useShareArticleColumn, useShareArticles } from '@features/commissioning/hooks';
import type { DocumentationSummaryRecord } from "@features/commissioning/hooks/useDocumentationSummaryPage";
import { formatWeekLabel, generatePdfFilename, isWeekInPast } from "@shared/utils";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

const shareArticleFilters = {
  is_harvest_share_article: true,
  is_active: true,
  is_purchased: true,
};

// PDF column widths
const widthShareArticle = "30%";
const widthAmountPerPu = "15%";
const widthTotalAmount = "15%";
const widthNote = "40%";

export default function PurchaseList() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedReseller, setSelectedReseller] = useState<string | null>(null);
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const [includeNextWeek, setIncludeNextWeek] = useState(false);

  const isMobile = useIsMobile();

  const { getUnitLabel } = useUnitOptions();
  const { format } = useNumberFormat();
  const { getSizeLabel } = useSizeOptions();
  const { sellers } = useSellers();
  const { noteColumn } = useNoteColumn();
  const selectedResellerLabel = useMemo(() => {
    if (!selectedReseller || !sellers) return null;
    const reseller = sellers.find(
      (seller: { value: string; label: string }) =>
        seller.value === selectedReseller,
    );
    return reseller?.label || selectedReseller;
  }, [selectedReseller, sellers]);

  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isOffice } = useRoles();

  const { shareArticleColumn, handleUnitChange } = useShareArticleColumn({
    filters: shareArticleFilters,
    showFruitsAndVegs: true,
    articleDefaults: "purchase",
  });

  const { refetch: refetchShareArticles } =
    useShareArticles(shareArticleFilters);

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
    overrides: {
      unit: {
        onFieldChange: handleUnitChange,
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

  const listParams =
    useMemo<CommissioningDocumentationSummarySummaryRetrieveParams>(
      () => ({
        year: selectedYear,
        delivery_week: selectedWeek ?? currentWeek,
        is_past: isPast,
        ...(includeNextWeek && { include_next_week: true }),
        model: "purchase",
        seller: selectedReseller ?? undefined,
        is_preparation_lists: true,
      }),
      [selectedYear, selectedWeek, includeNextWeek, selectedReseller, isPast],
    );

  const nextWeekParams =
    useMemo<CommissioningDocumentationSummarySummaryRetrieveParams>(() => {
      const week = selectedWeek ?? currentWeek;
      const nextWeek = week >= 52 ? 1 : week + 1;
      const nextYear = week >= 52 ? selectedYear + 1 : selectedYear;
      return {
        year: nextYear,
        delivery_week: nextWeek,
        is_past: false,
        model: "purchase",
        seller: selectedReseller ?? undefined,
        is_preparation_lists: true,
      };
    }, [selectedYear, selectedWeek, selectedReseller]);

  const { data: rawCurrentWeek, isFetching: currentWeekFetching } =
    useCommissioningDocumentationSummarySummaryRetrieve(listParams);

  const { data: rawNextWeek, isFetching: nextWeekFetching } =
    useCommissioningDocumentationSummarySummaryRetrieve(nextWeekParams, {
      query: { enabled: includeNextWeek },
    });

  // Both weeks feed the table; show the spinner while either is in flight.
  const isFetching = currentWeekFetching || nextWeekFetching;

  const data = useMemo(() => {
    // Directional cast at the orval boundary: the raw rows don't carry the
    // table-only ``key`` yet (EditableTable derives it from ``id``).
    const items = (rawCurrentWeek ?? []) as DocumentationSummaryRecord[];

    const filteredData = items.filter((item) => {
      return !!(
        item.theoretical_purchase_amount ||
        item.additional_theoretical_purchase_amount ||
        item.purchase_amount
      );
    });

    if (includeNextWeek && rawNextWeek) {
      const nextWeekItems = rawNextWeek as DocumentationSummaryRecord[];

      const nextWeekMap = new Map<string, DocumentationSummaryRecord>();
      for (const item of nextWeekItems) {
        const key = `${item.share_article}_${item.unit}_${item.size}`;
        nextWeekMap.set(key, item);
      }

      for (const item of filteredData) {
        const key = `${item.share_article}_${item.unit}_${item.size}`;
        const nw = nextWeekMap.get(key);
        item.next_week_theoretical = nw
          ? (nw.theoretical_purchase_amount ?? 0)
          : 0;
      }

      for (const [key, nwItem] of nextWeekMap) {
        const nwTheoretical = nwItem.theoretical_purchase_amount ?? 0;
        if (
          nwTheoretical &&
          !filteredData.some(
            (item) => `${item.share_article}_${item.unit}_${item.size}` === key,
          )
        ) {
          filteredData.push({
            ...nwItem,
            theoretical_purchase_amount: 0,
            additional_theoretical_purchase_amount: 0,
            // Synthesised next-week-only placeholder: no actual purchase
            // documented for the current week yet.
            purchase_amount: null,
            next_week_theoretical: nwTheoretical,
          });
        }
      }
    } else {
      for (const item of filteredData) {
        item.next_week_theoretical = 0;
      }
    }

    return filteredData;
  }, [rawCurrentWeek, rawNextWeek, includeNextWeek]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey:
        getCommissioningDocumentationSummarySummaryRetrieveQueryKey(listParams),
    });
    if (includeNextWeek) {
      queryClient.invalidateQueries({
        queryKey:
          getCommissioningDocumentationSummarySummaryRetrieveQueryKey(
            nextWeekParams,
          ),
      });
    }
  }, [queryClient, listParams, nextWeekParams, includeNextWeek]);
  const { onDeleteSuccess } = useInvalidateAfterTableMutation(invalidateData);

  // Save returns an ``AdditionalTheoretical*`` row; the list is the
  // joined summary shape. The optimistic-add can't reconcile that —
  // explicit invalidate so the new row appears in the right shape.
  // See CleaningList.tsx for the same rationale.
  const onSaveSuccess = useCallback(() => {
    invalidateData();
  }, [invalidateData]);

  const parseNumber = useCallback((value: unknown): number => {
    const num = parseFloat(value as string);
    return isNaN(num) ? 0 : num;
  }, []);

  // Process data to add computed fields
  const processedData = useMemo(() => {
    return data.map((record) => {
      const theoretical = parseNumber(record.theoretical_purchase_amount);
      const nextWeekTheoretical = parseNumber(record.next_week_theoretical);
      const inStock = parseNumber(record.theoretical_current_stock);
      const amountPerPu = parseNumber(record.amount_per_pu);
      const additionalPurchase = parseNumber(
        record.additional_theoretical_purchase_amount,
      );

      // Calculate amounts (current week only for stock-related)
      const stillInStockAmount = Math.max(inStock, 0);
      const toPurchaseAmount = Math.max(theoretical - stillInStockAmount, 0);

      // Combined = current + next week
      const combinedTheoretical = theoretical + nextWeekTheoretical;
      const combinedToPurchase = Math.max(
        combinedTheoretical - stillInStockAmount,
        0,
      );

      // Calculate theoretical purchase in PU (using combined when next week included)
      const effectiveToPurchase =
        nextWeekTheoretical > 0 ? combinedToPurchase : toPurchaseAmount;
      let theoreticalPurchaseInPu = 0;
      if (amountPerPu > 0 && effectiveToPurchase > 0) {
        theoreticalPurchaseInPu = Math.ceil(effectiveToPurchase / amountPerPu);
      }

      // Calculate additional purchase in PU
      let additionalPurchaseInPu = 0;
      if (additionalPurchase && amountPerPu > 0) {
        additionalPurchaseInPu = additionalPurchase / amountPerPu;
      }

      // Calculate total purchase list amount
      const totalPurchaseListAmount =
        theoreticalPurchaseInPu + additionalPurchaseInPu;

      // Format text representations. These strings end up in BOTH the
      // on-screen cell render AND the PDF (via the `dataKey` PDF option
      // below), so they have to be locale-aware — otherwise the user
      // sees "2.34 KG/PU" instead of "2,34 KG/PU" everywhere.
      const amountPerPuText =
        amountPerPu > 0
          ? `${format(amountPerPu, 2)} ${getUnitLabel(record.unit as string)}/${t("commissioning.pu")}`
          : "";

      const theoreticalPurchaseInPuText =
        theoreticalPurchaseInPu > 0
          ? `${format(theoreticalPurchaseInPu, 0)} ${t("commissioning.pu")}`
          : "";

      const additionalPurchaseInPuText =
        additionalPurchaseInPu > 0
          ? `${format(additionalPurchaseInPu, 2)} ${t("commissioning.pu")}`
          : "";

      const totalPurchaseListAmountText =
        totalPurchaseListAmount > 0
          ? `${format(totalPurchaseListAmount, 2)} ${t("commissioning.pu")}`
          : "";

      // Article name with size for PDF
      const sizeLabel =
        record.size && record.size !== "M"
          ? ` (${getSizeLabel(record.size as string)})`
          : "";
      const articleWithSize = `${record.share_article_name}${sizeLabel}`;

      return {
        ...record,
        // Computed amounts
        computed_still_in_stock: stillInStockAmount,
        computed_to_purchase: toPurchaseAmount,
        computed_to_purchase_combined: combinedToPurchase,
        computed_theoretical_purchase_in_pu: theoreticalPurchaseInPu,
        computed_additional_purchase_in_pu: additionalPurchaseInPu,
        computed_total_purchase_list_amount: totalPurchaseListAmount,
        computed_next_week_theoretical: nextWeekTheoretical,

        // Formatted text
        computed_amount_per_pu_text: amountPerPuText,
        computed_theoretical_purchase_in_pu_text: theoreticalPurchaseInPuText,
        computed_additional_purchase_in_pu_text: additionalPurchaseInPuText,
        computed_total_purchase_list_amount_text: totalPurchaseListAmountText,
        computed_article_with_size: articleWithSize,
        computed_unit_label: getUnitLabel(record.unit as string),
      };
    });
  }, [data, getUnitLabel, getSizeLabel, t, parseNumber, format]);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const parse = (value: unknown): number => {
        const num = parseFloat(value as string);
        return isNaN(num) ? 0 : num;
      };

      // Calculate amount based on additional_theoretical_purchase * amount_per_pu
      const manualAmountPu = parse(
        transformedData.additional_theoretical_purchase,
      );
      const amountPerPu = parse(transformedData.amount_per_pu);

      // Round to backend precision (DecimalField decimal_places=2). Without
      // this, `2.34 * 5` produces the IEEE-754 number 11.6999999...; JS's
      // shortest-roundtrip toString shows "11.7" so the JSON payload LOOKS
      // clean, but DRF parses it via Python float -> Decimal which
      // re-expands to 11.699999...928... — failing the decimal_places=2
      // validation. Rounding to 2 places here keeps the wire value canonical.
      const rawAmount = amountPerPu > 0 ? manualAmountPu * amountPerPu : 0;
      const calculatedAmount = Math.round(rawAmount * 100) / 100;

      return {
        ...transformedData,
        amount: calculatedAmount,
        year: selectedYear,
        delivery_week: selectedWeek ?? currentWeek,
        size: "M",
        model: "purchase",
        seller: selectedReseller,
      };
    },
    [selectedYear, selectedWeek, selectedReseller],
  );

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    // If it's a new row (key === -1), set default values
    if (record.key === -1) {
      const defaultValues = {
        size: "M",
      };

      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues };
    }

    const updatedRecord = {
      ...record,
      additional_theoretical_purchase: record.amount_per_pu
        ? Number(record.additional_theoretical_purchase_amount) /
          Number(record.amount_per_pu)
        : "",
    };

    form.setFieldsValue(updatedRecord);
    return updatedRecord;
  }, []);

  const columns: EditableColumnConfig<TableRecord>[] = [
    {
      ...shareArticleColumn,
      disabled: (record: Record<string, unknown>) => record.key != -1,
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
      title: <>{t("commissioning.theoretical_purchase")}</>,
      dataIndex: "theoretical_purchase_amount",
      key: "theoretical_purchase_amount",
      required: false,
      width: "9em",
      align: "center",
      disabled: true,
      hideInModal: true,
      hidden: isMobile,
      pdf: { include: false },
      render: (_: unknown, record: Record<string, unknown>) => {
        const current = parseNumber(record.theoretical_purchase_amount);
        const nw = parseNumber(record.computed_next_week_theoretical);
        if (!current && !nw) return "";
        return (
          <span>
            {current || ""}
            {nw > 0 && (
              <span className="text-purple-accent">
                {current ? ` + ${nw}` : nw}
              </span>
            )}
          </span>
        );
      },
    },
    {
      title: (
        <>
          {t("commissioning.still_in_stock")}
          <ToolTipIcon title={t("tooltip.still_in_stock_purchase")} />
        </>
      ),
      dataIndex: "computed_still_in_stock",
      key: "computed_still_in_stock",
      required: false,
      width: "9em",
      align: "center",
      disabled: true,
      hidden: isMobile,
      readOnly: true,
      hideInModal: true,
      pdf: { include: false },
    },
    {
      title: <>{t("commissioning.to_purchase")}</>,
      dataIndex: "computed_to_purchase",
      key: "computed_to_purchase",
      required: false,
      width: "9em",
      align: "center",
      disabled: true,
      hidden: isMobile,
      readOnly: true,
      pdf: { include: false },
      render: (_: unknown, record: Record<string, unknown>) => {
        const nw = parseNumber(record.computed_next_week_theoretical);
        if (nw > 0) {
          const combined = record.computed_to_purchase_combined as number;
          if (!combined) return "";
          return <span className="text-purple-accent">{combined}</span>;
        }
        const current = record.computed_to_purchase as number;
        return current || "";
      },
    },
    {
      title: <>{t("commissioning.amount_per_pu")}</>,
      dataIndex: "amount_per_pu",
      key: "amount_per_pu",
      inputType: "positive_decimal2",
      required: true,
      align: "center",
      width: "8em",
      render: (_: unknown, record: Record<string, unknown>) =>
        record.computed_amount_per_pu_text as ReactNode,
      pdf: {
        include: true,
        width: widthAmountPerPu,
        align: "center",
        title: t("commissioning.amount_per_pu"),
        dataKey: "computed_amount_per_pu_text",
      },
    },
    {
      title: <>{t("commissioning.theoretical_purchase_in_pu")}</>,
      dataIndex: "computed_theoretical_purchase_in_pu",
      key: "theoretical_purchase_in_pu",
      required: false,
      width: "9em",
      align: "center",
      disabled: true,
      hideInModal: true,
      hidden: isMobile,
    },
    {
      title: (
        <>
          {t("commissioning.additional_theoretical_purchase")}
          <ToolTipIcon title={t("tooltip.additional_theoretical_purchase")} />
        </>
      ),
      dataIndex: "additional_theoretical_purchase",
      key: "additional_theoretical_purchase",
      inputType: "negative_integer",
      required: false,
      align: "center",
      suffix: t("commissioning.pu"),
      width: "8em",
      render: (_: unknown, record: Record<string, unknown>) =>
        record.computed_additional_purchase_in_pu_text as ReactNode,
    },
    {
      title: <>{t("commissioning.amount_purchasing_list")}</>,
      dataIndex: "computed_total_purchase_list_amount_text",
      key: "amount_purchasing_list",
      required: false,
      width: "12em",
      align: "center",
      disabled: true,
      pdf: {
        include: true,
        width: widthTotalAmount,
        align: "center",
        title: t("commissioning.ordered_amount_purchasing_list"),
        dataKey: "computed_total_purchase_list_amount_text",
      },
    },
    {
      ...noteColumn,
      inputType: "optional",
      pdf: {
        include: true,
        width: widthNote,
        align: "left",
        title: t("commissioning.note"),
        dataKey: "note",
      },
    },
  ];

  const generateFilename = useMemo(() => {
    const weekLabel = includeNextWeek
      ? `${formatWeekLabel(selectedWeek, t)}+${nextWeekParams.delivery_week}`
      : formatWeekLabel(selectedWeek, t);
    return generatePdfFilename([
      t("commissioning.purchase_list"),
      selectedResellerLabel,
      selectedYear,
      weekLabel,
    ]);
  }, [
    selectedYear,
    selectedWeek,
    includeNextWeek,
    nextWeekParams.delivery_week,
    t,
    selectedResellerLabel,
  ]);

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

  return (
    <div>
      <h1>{t("commissioning.purchase_list")}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />
      <ResellerSelector
        selectedReseller={selectedReseller}
        setSelectedReseller={setSelectedReseller}
        userType="seller"
      />
      <div style={{ margin: "16px 0" }}>
        <Flex align="center" gap="8px" component="label">
          <Checkbox
            checked={includeNextWeek}
            onChange={(e) => setIncludeNextWeek(e.target.checked)}
            disabled={isPast}
          />
          <span>{t("commissioning.include_next_week")}</span>
        </Flex>
      </div>
      <PurchaseListPDFGenerator
        data={processedData}
        filename={generateFilename}
        buttonText={t("download.purchase_list")}
        title={t("commissioning.purchase_list_pdf", {
          resellerLabel: selectedResellerLabel,
        })}
        subtitle={
          includeNextWeek
            ? `${t("commissioning.KW")} ${selectedWeek}+${nextWeekParams.delivery_week}/${selectedYear}`
            : `${t("commissioning.KW")} ${selectedWeek}/${selectedYear}`
        }
        columns={columns}
      />

      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}
      <EditableTable
        key={`${selectedYear}-${selectedWeek}-${selectedReseller}-${includeNextWeek}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={processedData}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={{
          canAdd: !isPast && isOffice,
          canEdit: !isPast && isOffice,
          canDelete: false,
        }}
      />
      <AddShareArticleEntry
        disabled={isPast}
        defaultValues={{ is_purchased: true }}
        onSuccess={() => refetchShareArticles()}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.purchase_list")}
      </ExplainerText>
    </div>
  );
}
