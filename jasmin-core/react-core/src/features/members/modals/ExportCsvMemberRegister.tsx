import { useTranslation } from "react-i18next";
import { commissioningMembersExportCsvRetrieve } from "@shared/api/generated/commissioning/commissioning";
import ExportCsvDateRangeModal from "@features/commissioning/modals/csv/ExportCsvDateRangeModal";

interface ExportCsvMemberRegisterProps {
  open: boolean;
  onClose: () => void;
}

/**
 * GenG §30 Mitgliederliste export. Reuses the generic date-range CSV modal:
 * the office picks a window and downloads the member register (everyone who
 * was a member at any point in it, with Eintritt/Austritt + shares held).
 */
export default function ExportCsvMemberRegister({
  open,
  onClose,
}: ExportCsvMemberRegisterProps) {
  const { t } = useTranslation();
  return (
    <ExportCsvDateRangeModal
      open={open}
      onClose={onClose}
      title={t("members.export_member_register")}
      filenamePrefix="mitgliederliste"
      fetchCsv={(params) => commissioningMembersExportCsvRetrieve(params)}
    />
  );
}
