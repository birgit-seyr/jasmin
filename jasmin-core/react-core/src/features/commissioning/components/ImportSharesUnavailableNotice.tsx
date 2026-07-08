import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useTenant } from "@hooks/index";
import PastWarningMessage from "@shared/ui/PastWarningMessage";

interface ImportSharesUnavailableNoticeProps {
  /**
   * Name of the feature/view, interpolated into the default message
   * ("<feature> isn't available while …"). Omit for the generic wording.
   */
  feature?: string;
  /** Override the whole message (takes precedence over ``feature``). */
  children?: ReactNode;
  /** Hide the "Open CSV import" link (shown by default). */
  hideLink?: boolean;
  style?: CSSProperties;
  className?: string;
  width?: string;
}

/**
 * Warning shown on views that CANNOT work while the tenant sources weekly share
 * demand from the CSV import (``uploads_weekly_share_amount``). In that mode no
 * ``ShareDelivery`` rows exist — they're what per-member logistics reports
 * (box matrices, tour/pickup lists, station fees) read — so those pages would
 * silently show zeros. Drop this at the top of such a page to say so plainly.
 *
 * Self-gating: renders nothing for tenants on the normal subscription-driven
 * flow, so it's safe to mount unconditionally. This is the "not available"
 * sibling of ``ImportSharesModeBanner`` (which is a softer heads-up used where
 * the page still works but demand comes from the import).
 */
export default function ImportSharesUnavailableNotice({
  feature,
  children,
  hideLink = false,
  ...rest
}: ImportSharesUnavailableNoticeProps) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();

  const usesExternalDemand = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;
  if (!usesExternalDemand) return null;

  return (
    <PastWarningMessage {...rest}>
      {children ?? (
        <>
          {feature
            ? t("commissioning.import_shares_unavailable_named", { feature })
            : t("commissioning.import_shares_unavailable")}{" "}
          {!hideLink && (
            <Link to="/commissioning/import-shares">
              {t("commissioning.import_shares_unavailable_link")}
            </Link>
          )}
        </>
      )}
    </PastWarningMessage>
  );
}
