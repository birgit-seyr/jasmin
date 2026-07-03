import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCurrency } from "@hooks/index";
import { useCommissioningCrateNetPricesList } from "@shared/api/generated/commissioning/commissioning";
import ExportCsvAtDateModal, { type PriceColumn } from "./ExportCsvAtDateModal";

interface CrateNetPrice {
  name?: string;
  short_name?: string;
  price?: number | string;
  tax_rate?: number | string;
}

interface ExportCsvPricesCrateProps {
  open: boolean;
  onClose: () => void;
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
    <ExportCsvAtDateModal<CrateNetPrice>
      open={open}
      onClose={onClose}
      title={t("commissioning.export_crate_prices_for_date")}
      filenamePrefix={t("commissioning.crate_prices")}
      columns={columns}
      useListAtDate={
        useCommissioningCrateNetPricesList as unknown as Parameters<
          typeof ExportCsvAtDateModal<CrateNetPrice>
        >[0]["useListAtDate"]
      }
    />
  );
}
