import { Checkbox } from "antd";
import { useTranslation } from "react-i18next";
import type { ConsentDocument } from "@shared/api/generated/models";

const API_BASE = import.meta.env.VITE_API_URL || "";

interface Props {
  doc: ConsentDocument;
  accepted: boolean;
  onChange: (checked: boolean) => void;
  /** i18n key for the checkbox prefix text (before the document link). */
  labelKey?: string;
}

/**
 * Presentational consent checkbox: the document's title links to its PDF
 * (streamed by the public ``consent_documents/<id>/download_pdf/`` endpoint)
 * and the box records acceptance. The parent owns the ``doc`` (fetched via
 * {@link useCurrentConsentDoc}) so it knows whether the consent is required.
 *
 * Shared so the registration steps and the NewSubscriptionModal both use it.
 */
export default function ConsentDocumentField({
  doc,
  accepted,
  onChange,
  labelKey,
}: Props) {
  const { t } = useTranslation();
  const pdfUrl = `${API_BASE}/api/commissioning/consent_documents/${doc.id}/download_pdf/`;

  return (
    <Checkbox checked={accepted} onChange={(e) => onChange(e.target.checked)}>
      {t(labelKey ?? "consent.accept_prefix")}{" "}
      <a href={pdfUrl} target="_blank" rel="noopener noreferrer">
        {doc.title || t("consent.document")}
      </a>
    </Checkbox>
  );
}
