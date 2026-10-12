import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button } from "antd";
import { useTranslation } from "react-i18next";

import { useTimeFormat } from "@hooks/index";
import {
  getCommissioningMembersListQueryKey,
  getCommissioningMembersRetrieveQueryKey,
  useCommissioningMembersMarkConsentReviewedCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

/**
 * Tells the office that the member withdrew their consent to the privacy
 * policy or the withdrawal terms, and when: whatever rested on it may have to
 * stop. Marking the review done clears the warning; the withdrawal itself
 * stays on the member's consent record. Office only.
 */
export default function ConsentWithdrawalAlert({ member }: { member: Member }) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { formatDateTimeWithFallback } = useTimeFormat();
  const queryClient = useQueryClient();
  const { mutate: markReviewed, isPending } =
    useCommissioningMembersMarkConsentReviewedCreate({
      mutation: {
        meta: { silent: true },
        onSuccess: () => {
          notify.success(t("consent.review.marked_done"));
          void queryClient.invalidateQueries({
            queryKey: getCommissioningMembersRetrieveQueryKey(member.id),
          });
          // The members list's "consent withdrawn" chip counts this member.
          void queryClient.invalidateQueries({
            queryKey: getCommissioningMembersListQueryKey(),
          });
        },
        onError: (error) => notify.error(getErrorMessage(error)),
      },
    });

  const memberId = member.id;
  if (!isOffice || !member.consent_withdrawn_at || !memberId) return null;

  return (
    <Alert
      className="member-consent-review-alert"
      type="warning"
      showIcon
      message={t("consent.review.title", {
        date: formatDateTimeWithFallback(member.consent_withdrawn_at, "—"),
      })}
      description={t("consent.review.description")}
      action={
        <Button
          size="small"
          loading={isPending}
          onClick={() => markReviewed({ id: memberId })}
        >
          {t("consent.review.mark_done")}
        </Button>
      }
    />
  );
}
