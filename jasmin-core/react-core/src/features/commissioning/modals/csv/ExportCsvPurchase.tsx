import { useTranslation } from "react-i18next";
import { commissioningPurchaseExportCsvRetrieve } from "@shared/api/generated/commissioning/commissioning";
import ExportCsvDateRangeModal from "./ExportCsvDateRangeModal";

interface ExportCsvPurchaseProps {
  open: boolean;
  onClose: () => void;
}

export default function ExportCsvPurchase({
  open,
  onClose,
}: ExportCsvPurchaseProps) {
  const { t } = useTranslation();
  return (
    <ExportCsvDateRangeModal
      open={open}
      onClose={onClose}
      title={t("commissioning.csv_export_purchase")}
      filenamePrefix="zukauf"
      fetchCsv={(params) => commissioningPurchaseExportCsvRetrieve(params)}
      options={[
        {
          key: "summed",
          label: t("commissioning.sum_by_share_article"),
          filenameSuffix: "_summiert",
        },
      ]}
    />
  );
}
