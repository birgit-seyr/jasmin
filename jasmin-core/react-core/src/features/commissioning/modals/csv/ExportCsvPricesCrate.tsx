import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency } from "@hooks/index";
import { useCommissioningCrateNetPricesList } from "@shared/api/generated/commissioning/commissioning";
import ExportCsvAtDateModal, { type PriceColumn } from "./ExportCsvAtDateModal";

interface ExportCsvPricesCrateProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Row supplier: the crate-prices endpoint has no date param, so it returns the
 * current crate net prices regardless of the picked date (the date only names
 * the export file). Gated on `loadedDate` so nothing is fetched before Load.
 */
function useCrateRowsAtDate(loadedDate: string | null) {
  const { data, isLoading } = useCommissioningCrateNetPricesList(
    {},
    { query: { enabled: !!loadedDate } },
  );
  return {
    rows: (data ?? null) as unknown as Record<string, unknown>[] | null,
    isLoading,
  };
}

export default function ExportCsvPricesCrate({
  open,
  onClose,
}: ExportCsvPricesCrateProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();

  const columns: PriceColumn[] = useMemo(
    () => [
      { key: "short_name", label: t("commissioning.name") },
      { key: "name", label: t("commissioning.name") },
      { key: "price", label: `${t("commissioning.price")} (${currencySymbol})` },
      { key: "tax_rate", label: t("commissioning.tax_rate") },
    ],
    [t, currencySymbol],
  );

  return (
    <ExportCsvAtDateModal
      open={open}
      onClose={onClose}
      title={t("commissioning.export_crate_prices_for_date")}
      filenamePrefix={t("commissioning.crate_prices")}
      columns={columns}
      useRows={useCrateRowsAtDate}
    />
  );
}
