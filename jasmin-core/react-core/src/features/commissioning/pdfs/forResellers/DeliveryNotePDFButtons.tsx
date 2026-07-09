import { Button, type ButtonProps } from "antd";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { commissioningDeliveryNotesRetrieve } from "@shared/api/generated/commissioning/commissioning";
import { notify } from "@shared/utils";
import { openStoredPdf } from "./pdfDownload";

/**
 * Lightweight delivery-note download button.
 *
 * Unlike `DeliveryNotePDFGenerator` (which fetches the delivery note +
 * converts the logo on mount so it can show a `<PDFViewer>` in
 * `viewMode`), this component does NO work until the user actually clicks.
 * Use it inside table rows / lists.
 */
interface DeliveryNotePDFButtonsProps {
  deliveryNoteId: string | null;
  buttonText?: string;
  buttonSize?: "small" | "middle" | "large";
  /** Override the AntD button type (defaults to "primary"). */
  buttonType?: ButtonProps["type"];
  /** Optional leading icon; pass buttonText="" for an icon-only button. */
  icon?: ReactNode;
  className?: string;
  /**
   * Accessible name used only in icon-only mode (`buttonText=""`). When a
   * visible `buttonText` is present it already names the button, so this is
   * ignored.
   */
  ariaLabel?: string;
}

export default function DeliveryNotePDFButtons({
  deliveryNoteId,
  buttonText,
  buttonSize = "middle",
  buttonType = "primary",
  icon,
  className,
  ariaLabel,
}: DeliveryNotePDFButtonsProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);

  const handlePDFDownload = async () => {
    if (!deliveryNoteId) return;
    setLoading(true);
    try {
      const dn = await commissioningDeliveryNotesRetrieve(deliveryNoteId);
      if (!dn.file) {
        notify.error(t("commissioning.pdf_not_available"));
        return;
      }
      openStoredPdf(dn.file);
    } catch (err) {
      console.error("Failed to load delivery note for PDF download:", err);
      notify.error(t("common.error_loading_data"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      type={buttonType}
      size={buttonSize}
      icon={icon}
      className={className}
      aria-label={
        buttonText
          ? undefined
          : (ariaLabel ?? t("commissioning.download_delivery_note"))
      }
      onClick={handlePDFDownload}
      loading={loading}
      disabled={!deliveryNoteId || loading}
    >
      {buttonText ?? t("commissioning.download_pdf")}
    </Button>
  );
}
