import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningOrganicCertificatesCreate,
  commissioningOrganicCertificatesDestroy,
  commissioningOrganicCertificatesPartialUpdate,
  getCommissioningOrganicCertificatesListQueryKey,
  useCommissioningOrganicCertificatesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { OrganicCertificate } from "@shared/api/generated/models";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import { useTimeBoundColumns } from "@hooks/index";
import PriceEditorModal from "./prices/PriceEditorModal";

interface OrganicCertificatesModalProps {
  visible: boolean;
  onClose: () => void;
  reseller: string | null;
  reseller_name: string;
}

/**
 * Manage a seller's time-bound organic certificates. Reuses the generic
 * `PriceEditorModal` (a single-FK time-bound editor) + `useTimeBoundColumns`,
 * so it inherits the succession-aware save/refetch, delete gating and the
 * valid-from/until pickers unchanged.
 */
export default function OrganicCertificatesModal({
  visible,
  onClose,
  reseller,
  reseller_name,
}: OrganicCertificatesModalProps) {
  const { t } = useTranslation();
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns();

  const columns = useMemo<EditableColumnConfig[]>(
    () =>
      [
        validFromColumn,
        validUntilColumn,
        {
          title: <>{t("resellers.organic_certificate_number")}</>,
          dataIndex: "certificate_number",
          key: "certificate_number",
          inputType: "text",
          required: false,
          width: "10em",
        },
        {
          title: <>{t("resellers.organic_certificate_link")}</>,
          dataIndex: "link",
          key: "link",
          inputType: "text",
          required: false,
          width: "16em",
          render: (value: unknown) =>
            value ? (
              <a
                href={value as string}
                target="_blank"
                rel="noreferrer noopener"
              >
                {value as string}
              </a>
            ) : (
              ""
            ),
        },
      ] as EditableColumnConfig[],
    [t, validFromColumn, validUntilColumn],
  );

  return (
    <PriceEditorModal<OrganicCertificate, OrganicCertificate>
      visible={visible}
      onClose={onClose}
      title={
        <div>
          {t("resellers.organic_certificates_for")} {reseller_name}
        </div>
      }
      width={800}
      fkField="reseller"
      fkValue={reseller}
      intro={<></>}
      pagination={false}
      columns={columns}
      listHook={useCommissioningOrganicCertificatesList}
      getListQueryKey={getCommissioningOrganicCertificatesListQueryKey}
      api={{
        create: commissioningOrganicCertificatesCreate,
        partialUpdate: commissioningOrganicCertificatesPartialUpdate,
        destroy: commissioningOrganicCertificatesDestroy,
      }}
    />
  );
}
