import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { useOnboardingMode } from "@hooks/index";
import DisabledReasonTooltip from "@shared/ui/DisabledReasonTooltip";

interface WaitingListOfferButtonProps {
  /** Opens the review-and-send offer modal for the row. */
  onClick: () => void;
}

/**
 * "Notify member" on a claimable waiting-list row. Offering a spot emails the
 * member, so the button is disabled while the tenant's onboarding mode is on
 * (the server refuses ``offer_spot`` then) and a hover tooltip says why.
 */
export function WaitingListOfferButton({ onClick }: WaitingListOfferButtonProps) {
  const { t } = useTranslation();
  const onboardingMode = useOnboardingMode();

  return (
    <DisabledReasonTooltip
      reason={onboardingMode ? t("onboarding.mode.offer_spot_disabled") : null}
    >
      {(reasonId) => (
        <Button
          size="small"
          type="primary"
          onClick={onClick}
          disabled={onboardingMode}
          aria-describedby={reasonId}
        >
          {t("abos.notify_member")}
        </Button>
      )}
    </DisabledReasonTooltip>
  );
}
