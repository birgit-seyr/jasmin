/**
 * Harvesting list page. Deliberately thin: UI state (selected
 * year/week/day, office/gardener view) and layout live here; the data
 * pipeline is ``useHarvestingListData``, every column shape is
 * ``useHarvestingListColumns``, and the larger UI sections are
 * components under ``./components/``.
 */

import type { FormInstance } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreate,
  commissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationSummaryAddAdditionalTheoreticalAmountCreateBody,
  CommissioningDocumentationSummaryUpdateAdditionalTheoreticalAmountPartialUpdateBody,
  Harvest,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  HarvestConfirmationModal,
  HarvestingMobileCard,
  useHarvestConfirmation,
} from "@features/commissioning/components/mobileCards";
// Typed wrapper that internally lazy-imports the PDF template + the
// @react-pdf/renderer library. The library only loads when the user
// clicks Download — see HarvestingListPDFGenerator / ListPDFGenerator
// for the click-to-load architecture.
import HarvestingListPDFGenerator from "@features/commissioning/pdfs/exports/HarvestingListPDFGenerator";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, MobileStack, PastWarningMessage } from "@shared/ui";
import {
  RelatedDayInfo,
  VariationsTotalsCard,
} from "@features/commissioning/components";
import { useIsMobile, useTenantSettingToggle } from "@hooks/index";
import {
  useHarvestingListColumns,
  useHarvestingListData,
} from "@features/commissioning/hooks";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  isWeekInPast,
} from "@shared/utils";
import HarvestingCrateSummary from "@features/commissioning/components/HarvestingCrateSummary";
import HarvestingListControls from "@features/commissioning/components/HarvestingListControls";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();
const currentDay = dayjs().isoWeekday();

export default function HarvestingList() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDay, setSelectedDay] = useState<number | null>(currentDay - 1);
  const isPast = useMemo(
    () => isWeekInPast(selectedYear, selectedWeek),
    [selectedYear, selectedWeek],
  );
  const isMobile = useIsMobile();
  const { canEdit } = useRoles();
  const [isGardenerView, setIsGardenerView] = useState(isMobile);
  const { t } = useTranslation();

  const { value: roundUpToFullPU, onChange: handleRoundUpToFullVPEChange } =
    useTenantSettingToggle("round_up_to_full_pu_harvesting", false);

  // Force gardener view on mobile
  useEffect(() => {
    if (isMobile) setIsGardenerView(true);
  }, [isMobile]);

  const {
    loading,
    isFetching,
    filteredData,
    pdfData,
    plotGroupFirstIds,
    crateSummary,
    deliveryDaysForHarvesting,
    variationsTotalsFilters,
    variationsTotals,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
  } = useHarvestingListData({
    selectedYear,
    selectedWeek,
    selectedDay,
    isPast,
    isGardenerView,
    roundUpToFullPU,
  });

  const { columns, pdfColumns } = useHarvestingListColumns({
    isMobile,
    isGardenerView,
  });

  const harvestConfirmation = useHarvestConfirmation({
    selectedYear,
    selectedWeek,
    selectedDay,
    fallbackWeek: currentWeek,
    onSaved: invalidateData,
  });

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      return {
        ...transformedData,
        year: selectedYear,
        delivery_week: selectedWeek,
        day_number: selectedDay,
        model: "harvest",
      };
    },
    [selectedYear, selectedWeek, selectedDay],
  );

  const customEdit = useCallback((record: TableRecord, form: FormInstance) => {
    if (record.key === -1) {
      const defaultValues = {
        size: "M",
      };

      form.setFieldsValue(defaultValues);

      return { ...record, ...defaultValues } as TableRecord;
    }

    const updatedRecord = {
      ...record,
      amount_share_content:
        (record.additional_theoretical_harvest_amount_share_content as number) ||
        0,
      amount_order_content:
        (record.additional_theoretical_harvest_amount_order_content as number) ||
        0,
    };

    form.setFieldsValue(updatedRecord);

    return updatedRecord as TableRecord;
  }, []);

  const generateFilename = useMemo(() => {
    return generatePdfFilename([
      t("commissioning.harvesting_list"),
      selectedYear,
      formatWeekLabel(selectedWeek, t),
      formatDayLabel(selectedDay, t),
    ]);
  }, [selectedYear, selectedWeek, selectedDay, t]);

  // No ``list`` here: the page owns the data (``useHarvestingListData``
  // → ``initialData``), so the table must never fetch it itself.
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

  // Harvesting: add is hidden in the gardener/mobile views; edit + add both
  // require a non-past week and edit permission; rows are never deleted here.
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
      <h1>{t("commissioning.harvesting_list")}</h1>
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
          suffix={t("commissioning.harvesting_day")}
        />
      </MobileStack>

      {!isMobile && (
        <RelatedDayInfo
          label={t("commissioning.delivery_day_shares")}
          relatedDayNumbers={deliveryDaysForHarvesting}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedYear={selectedYear}
        />
      )}

      <HarvestingListControls
        isMobile={isMobile}
        isGardenerView={isGardenerView}
        onViewChange={setIsGardenerView}
        roundUpToFullPU={roundUpToFullPU}
        onRoundUpChange={handleRoundUpToFullVPEChange}
      />

      {!isMobile && (
        <HarvestingListPDFGenerator
          data={pdfData}
          dataFirstPageOnly={crateSummary}
          variationsTotals={variationsTotals}
          filename={generateFilename}
          buttonText={t("download.harvesting_list")}
          pill={t("commissioning.harvesting_list")}
          title={`${t(
            "commissioning.KW",
          )} ${selectedWeek}/${selectedYear} · ${getDayName(selectedDay, t)}`}
          subtitle=""
          columns={pdfColumns}
        />
      )}
      {isPast && (
        <PastWarningMessage>{t("table.past_week_readonly")}</PastWarningMessage>
      )}

      <VariationsTotalsCard
        filters={variationsTotalsFilters}
        tooltip={t("tooltip.variations_totals_packing_list_boxes")}
      />

      <EditableTable
        key={`${selectedYear}-${selectedWeek}-${selectedDay}`}
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_article_name"
        initialData={filteredData}
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
        renderMobileCard={(
          record: TableRecord,
          onEdit: (r: TableRecord) => void,
        ) => (
          <HarvestingMobileCard
            key={String(record.key)}
            record={record}
            onEdit={onEdit}
            onConfirmHarvest={harvestConfirmation.open}
            showPlotHeader={plotGroupFirstIds.has(record.key)}
            isConfirmed={harvestConfirmation.isConfirmed(record)}
            isPast={isPast}
          />
        )}
      />

      <HarvestingCrateSummary
        crateSummary={crateSummary}
        isMobile={isMobile}
        showMobileCard={!loading && filteredData.length > 0}
      />

      <HarvestConfirmationModal
        record={harvestConfirmation.record}
        amount={harvestConfirmation.amount}
        saving={harvestConfirmation.saving}
        onChangeAmount={harvestConfirmation.setAmount}
        onCancel={harvestConfirmation.close}
        onConfirm={harvestConfirmation.confirm}
      />

      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.harvesting_list")}
        </ExplainerText>
      )}
    </div>
  );
}
