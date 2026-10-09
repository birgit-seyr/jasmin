import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningBulkSendDocumentsViaEmailCreate } from "@shared/api/generated/commissioning/commissioning";
import type {
  CombinedOrderOverview,
  ModelEnum,
} from "@shared/api/generated/models";
import { BulkActionButton } from "@shared/ui";
import { JobProgressDrawer } from "@shared/ui/JobProgressDrawer";

interface BulkSendDocumentsButtonProps {
  model: ModelEnum;
  rows: CombinedOrderOverview[];
  selectedIds: (string | number)[];
  /** Runs when the progress drawer closes, so the page can show the new
   * "sent" stamps. */
  onClose: () => void;
}

/**
 * Emails the invoices or delivery notes (``model``) of the selected orders to
 * their resellers. Only the orders whose document is finalized are sent, and
 * the button stays disabled until the selection holds one. The send runs as a
 * background job, followed in a drawer that lists each order's outcome.
 */
export default function BulkSendDocumentsButton({
  model,
  rows,
  selectedIds,
  onClose,
}: BulkSendDocumentsButtonProps) {
  const { t } = useTranslation();
  const [jobId, setJobId] = useState<string | null>(null);
  const finalizedOrderIds = useMemo(
    () =>
      rows
        .filter(
          (row) =>
            selectedIds.includes(row.id) &&
            (model === "invoice"
              ? row.has_finalized_invoice
              : row.delivery_note_is_finalized),
        )
        .map((row) => row.id),
    [rows, selectedIds, model],
  );
  const label =
    model === "invoice"
      ? t("resellers.send_via_email_resellers")
      : t("commissioning.send_delivery_notes_bulk_via_email");

  return (
    <>
      <BulkActionButton
        selectedIds={finalizedOrderIds}
        apiFunction={(payload) =>
          commissioningBulkSendDocumentsViaEmailCreate({
            ids: payload.ids,
            model,
          })
        }
        buttonText={label}
        buttonProps={{ type: "primary" }}
        onSuccess={(response) => setJobId(response.job_id ?? null)}
      />
      <JobProgressDrawer
        jobId={jobId}
        title={label}
        onClose={() => {
          setJobId(null);
          onClose();
        }}
      />
    </>
  );
}
