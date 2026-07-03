import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningShareArticleNetPricesList } from "@shared/api/generated/commissioning/commissioning";
import type { ShareArticleNetPrice } from "@shared/api/generated/models/shareArticleNetPrice";
import ExportCsvAtDateModal, { type PriceColumn } from "./ExportCsvAtDateModal";
import { useSharePriceCsvColumns } from "./useSharePriceCsvColumns";

interface ExportCsvPricesShareArticleProps {
  open: boolean;
  onClose: () => void;
}

export default function ExportCsvPricesShareArticle({
  open,
  onClose,
}: ExportCsvPricesShareArticleProps) {
  const { t } = useTranslation();
  const priceColumns = useSharePriceCsvColumns();

  // Standalone price export keys the row's name off the annotated
  // `share_article_name` (the prices endpoint joins it onto each
  // ShareArticleNetPrice row).
  const columns: PriceColumn[] = useMemo(
    () => [
      { key: "share_article_name", label: t("commissioning.name") },
      ...priceColumns,
    ],
    [t, priceColumns],
  );

  return (
    <ExportCsvAtDateModal<ShareArticleNetPrice>
      open={open}
      onClose={onClose}
      title={t("commissioning.export_prices_for_date")}
      filenamePrefix={t("commissioning.prices")}
      columns={columns}
      useListAtDate={
        useCommissioningShareArticleNetPricesList as unknown as Parameters<
          typeof ExportCsvAtDateModal<ShareArticleNetPrice>
        >[0]["useListAtDate"]
      }
    />
  );
}
