import { useTranslation } from "react-i18next";
import { commissioningSharesExportCsvRetrieve } from "@shared/api/generated/commissioning/commissioning";
import ExportCsvDateRangeModal from "./ExportCsvDateRangeModal";

interface ExportCsvShareWeightsProps {
  open: boolean;
  onClose: () => void;
}

export default function ExportCsvShareWeights({
  open,
  onClose,
}: ExportCsvShareWeightsProps) {
  const { t } = useTranslation();
  return (
    <ExportCsvDateRangeModal
      open={open}
      onClose={onClose}
      title={t("commissioning.export_share_weights_csv")}
      filenamePrefix="anteilsgewichte"
      fetchCsv={(params) => commissioningSharesExportCsvRetrieve(params)}
    />
  );
}
