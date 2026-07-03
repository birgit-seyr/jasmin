import { useTranslation } from "react-i18next";
import { commissioningHarvestExportCsvRetrieve } from "@shared/api/generated/commissioning/commissioning";
import ExportCsvDateRangeModal from "./ExportCsvDateRangeModal";

interface ExportCsvHarvestProps {
  open: boolean;
  onClose: () => void;
}

export default function ExportCsvHarvest({
  open,
  onClose,
}: ExportCsvHarvestProps) {
  const { t } = useTranslation();
  return (
    <ExportCsvDateRangeModal
      open={open}
      onClose={onClose}
      title={t("commissioning.export_harvest_csv")}
      filenamePrefix="ernte"
      fetchCsv={(params) => commissioningHarvestExportCsvRetrieve(params)}
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
