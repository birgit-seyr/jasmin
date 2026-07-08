import { Space } from "antd";
import { useTranslation } from "react-i18next";
import PrivacyPolicyEditorCard from "@features/configuration/components/PrivacyPolicyEditorCard";
import VVTControllerFieldsCard from "@features/configuration/components/VVTControllerFieldsCard";
import VVTExportCard from "@features/configuration/components/VVTExportCard";

/**
 * Admin GDPR configuration (tenant settings — stays in Configuration):
 *  - the public privacy policy (Datenschutzerklärung)
 *  - the Art. 30 VVT records: controller-identity fields + the Verzeichnis export
 *
 * The deletion-request queue (member offboarding) moved to the Members section
 * (``GdprDeletionRequests``).
 */
export default function ConfigurationGDPR() {
  const { t } = useTranslation();

  return (
    <>
      <h1>{t("gdpr.title")}</h1>
      <Space direction="vertical" size="middle" className="w-full">
        <PrivacyPolicyEditorCard />
        {/* Art. 30 VVT: the controller-identity fields (legal form, DPO,
            data-protection contact, supervisory authority) feed the export
            below, then the export itself. */}
        <VVTControllerFieldsCard />
        <VVTExportCard />
      </Space>
    </>
  );
}
