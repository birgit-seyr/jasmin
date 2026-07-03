import { useRoles } from "@shared/auth";
import { CleaningListPDFGenerator } from "@features/commissioning/pdfs";
import AdditionalTheoreticalSummaryList from "@features/commissioning/components/AdditionalTheoreticalSummaryList";

export default function CleaningList() {
  // Cleaning is editable by gardener/staff/office/admin (washing is
  // office-only — see WashingList). Pre-existing drift, preserved per page.
  const { canEdit } = useRoles();

  return (
    <AdditionalTheoreticalSummaryList
      model="cleanamount"
      canEdit={canEdit}
      titleKey="commissioning.cleaning_list"
      daySuffixKey="commissioning.cleaning_day"
      teamViewLabelKey="commissioning.clean_team_view"
      explainerKey="explainers.cleaning_list"
      theoreticalColumnTitleKey="commissioning.theoretical_clean_amounts"
      toProcessColumnTitleKey="commissioning.to_clean"
      additionalColumnTitleKey="commissioning.additional_theoretical_clean"
      additionalTooltipKey="tooltip.additional_theoretical_clean_amount"
      amountColumnTitleKey="commissioning.amount_cleaning_list"
      totalAmountTextField="computed_total_clean_amount_text"
      renderPdf={(data, { year, week, dayName, filename, t }) => (
        <CleaningListPDFGenerator
          data={data}
          year={year}
          week={week}
          dayName={dayName}
          filename={filename}
          buttonText={t("download.cleaning_list")}
          t={t}
        />
      )}
    />
  );
}
