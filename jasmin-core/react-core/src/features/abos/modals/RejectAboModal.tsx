import type { FC } from "react";
import { useTranslation } from "react-i18next";

import { AdminRejectionModal } from "@shared/modals/AdminRejectionModal";
import type { AboRecord } from "@features/abos/pages/types";
import { useVariationLabel } from "@hooks/index";

interface RejectAboModalProps {
  isOpen: boolean;
  onClose: () => void;
  abo: AboRecord | null;
  reason: string;
  onReasonChange: (value: string) => void;
  onReject: () => void;
  loading?: boolean;
}

/**
 * Reject a pending subscription ("Abo") with an optional reason. Thin
 * wrapper over the shared {@link AdminRejectionModal} that supplies
 * the subscription-specific copy.
 *
 * The reason is stored on ``Subscription.admin_rejection_reason`` and is
 * currently NOT emailed to the member (no subscription-rejection email
 * template ships today). Wire one up alongside the P2 follow-up if
 * product asks.
 */
export const RejectAboModal: FC<RejectAboModalProps> = ({
  isOpen,
  onClose,
  abo,
  reason,
  onReasonChange,
  onReject,
  loading = false,
}) => {
  const { t } = useTranslation();
  const variationLabel = useVariationLabel();

  if (!abo) return null;

  return (
    <AdminRejectionModal
      isOpen={isOpen}
      onClose={onClose}
      reason={reason}
      onReasonChange={onReasonChange}
      onReject={onReject}
      loading={loading}
      title={t("members.reject_abo_modal_title")}
      heading={
        <>
          {abo.member_first_name} {abo.member_last_name}
          {abo.share_type_variation_string
            ? ` — ${variationLabel(abo.share_type_variation_string)}`
            : ""}
        </>
      }
      warningTitle={t("members.reject_abo_warning_title")}
      warningBody={t("members.reject_abo_warning_body")}
      reasonPlaceholder={t("members.reject_reason_placeholder")}
    />
  );
};
