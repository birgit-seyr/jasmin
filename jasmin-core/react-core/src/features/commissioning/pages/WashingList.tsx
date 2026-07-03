import { useRoles } from "@shared/auth";
import { WashingMobileCard } from "@features/commissioning/components/mobileCards";
import { WashingListPDFGenerator } from "@features/commissioning/pdfs";
import AdditionalTheoreticalSummaryList from "@features/commissioning/components/AdditionalTheoreticalSummaryList";

export default function WashingList() {
  // Washing is office-only (cleaning is broader — see CleaningList). This
  // pre-existing permission drift is preserved deliberately per page.
  const { isOffice } = useRoles();

  return (
    <AdditionalTheoreticalSummaryList
      model="washamount"
      canEdit={isOffice}
      titleKey="commissioning.washing_list"
      daySuffixKey="commissioning.washing_day"
      teamViewLabelKey="commissioning.wash_team_view"
      explainerKey="explainers.washing_list"
      theoreticalColumnTitleKey="commissioning.theoretical_harvest"
      toProcessColumnTitleKey="commissioning.to_wash"
      additionalColumnTitleKey="commissioning.additional_theoretical_wash"
      additionalTooltipKey="tooltip.additional_theoretical_wash_amount"
      amountColumnTitleKey="commissioning.amount_washing_list"
      totalAmountTextField="computed_total_wash_amount_text"
      renderPdf={(data, { year, week, dayName, filename, t }) => (
        <WashingListPDFGenerator
          data={data}
          year={year}
          week={week}
          dayName={dayName}
          filename={filename}
          buttonText={t("download.washing_list")}
          t={t}
        />
      )}
      renderMobileCard={(record, onEdit) => (
        <WashingMobileCard
          key={String(record.key)}
          record={record}
          onEdit={onEdit}
        />
      )}
    />
  );
}
