import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Alert, Typography } from "antd";
import type { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useTimeFormat } from "@hooks/index";

const { Paragraph } = Typography;

export type ModalStatusBannerKind = "rejected" | "confirmed" | "cancelled";

interface ModalStatusBannerProps {
  /**
   * The terminal state the modal is decorating. Drives the Alert
   * colour, icon, and default title:
   *
   *   rejected  → red,    "This application was rejected."
   *   confirmed → green,  "This application is confirmed."
   *   cancelled → gray,   "This row is cancelled."
   */
  kind: ModalStatusBannerKind;
  /**
   * ISO timestamp of when the state was set. When provided, renders
   * a "{label}: {formatted timestamp}" line (e.g. "Rejected on:
   * 2026-06-05 14:23"). When null/undefined, the line is omitted.
   */
  at?: string | null;
  /**
   * Free-text reason supplied by the office when they took the
   * action. When provided, renders an italicized "Reason: ..." line.
   * When null/undefined or empty, the line is omitted.
   */
  reason?: string | null;
  /**
   * Override the default banner title. Pass a ReactNode (string or
   * a translated t() call) when the default copy doesn't fit.
   */
  title?: ReactNode;
  /**
   * Override the default i18n key for the "Rejected on"/"Confirmed
   * on"/"Cancelled on" prefix. Useful when a modal wants its own
   * domain term (e.g. "Austrittsdatum" instead of generic
   * "Cancelled on").
   */
  atLabel?: ReactNode;
}

/**
 * Terminal-state banner shown inside admin-confirmation /
 * detail modals. Encapsulates the "this record is done — here's the
 * decision metadata" affordance that AdminConfirmationModalMembers
 * and AdminConfirmationModalAbos render verbatim today.
 *
 * The Alert colour + icon + default title are picked from ``kind``;
 * ``at`` and ``reason`` render as optional secondary lines when
 * present. Date formatting flows through ``useTimeFormat`` so the
 * tenant-configured date format wins consistently across modals.
 */
export const ModalStatusBanner: FC<ModalStatusBannerProps> = ({
  kind,
  at,
  reason,
  title,
  atLabel,
}) => {
  const { t } = useTranslation();
  const { formatDateTime } = useTimeFormat();

  const config = (() => {
    switch (kind) {
      case "rejected":
        return {
          alertType: "error" as const,
          icon: <CloseCircleOutlined />,
          defaultTitle: t("members.rejected_banner_title"),
          defaultAtLabel: t("members.rejected_at_label"),
        };
      case "confirmed":
        return {
          alertType: "success" as const,
          icon: <CheckCircleOutlined />,
          defaultTitle: t("members.confirmed_banner_title"),
          defaultAtLabel: t("members.confirmed_at_label"),
        };
      case "cancelled":
        return {
          alertType: "warning" as const,
          icon: <StopOutlined />,
          defaultTitle: t("members.cancelled_banner_title"),
          defaultAtLabel: t("members.cancelled_at_label"),
        };
    }
  })();

  const hasAt = !!at;
  const hasReason = !!(reason && reason.length > 0);

  return (
    <Alert
      type={config.alertType}
      showIcon
      icon={config.icon}
      style={{ marginBottom: 16 }}
      message={title ?? config.defaultTitle}
      description={
        hasAt || hasReason ? (
          <div>
            {hasAt && (
              <Paragraph style={{ marginBottom: hasReason ? 4 : 0 }}>
                {atLabel ?? config.defaultAtLabel}: {formatDateTime(at!)}
              </Paragraph>
            )}
            {hasReason && (
              <Paragraph style={{ marginBottom: 0 }}>
                {t("members.reject_reason_label")}:{" "}
                <em>{reason}</em>
              </Paragraph>
            )}
          </div>
        ) : undefined
      }
    />
  );
};

export default ModalStatusBanner;
