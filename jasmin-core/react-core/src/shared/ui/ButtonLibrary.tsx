import type { CSSProperties, ReactNode } from "react";
import { Button, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import {
  BankOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CreditCardOutlined,
  EyeOutlined,
  UserOutlined,
  MailOutlined,
  ExclamationCircleOutlined,
  HistoryOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";

type ButtonType = "default" | "primary" | "dashed" | "text" | "link";
type ButtonSize = "small" | "middle" | "large";

interface ButtonConfig {
  type?: ButtonType;
  size?: ButtonSize;
  icon?: ReactNode;
  className?: string;
  /** i18n key for the tooltip + accessible name — resolved via ``t()`` in the
   *  button so a caller that omits a ``tooltip`` never surfaces raw English. */
  labelKey: string;
  style?: CSSProperties;
  danger?: boolean;
}

// Only variants actually referenced anywhere in the codebase are kept.
const BUTTON_CONFIGS: Record<string, ButtonConfig> = {
  view: {
    type: "text",
    size: "small",
    icon: <EyeOutlined className="lib-status-icon" />,
    labelKey: "button_library.view",
    className: "small-squared-button",
  },
  logging: {
    type: "text",
    icon: (
      <HistoryOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.logging",
  },
  emails: {
    type: "text",
    icon: (
      <MailOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.emails",
  },
  coopshares: {
    type: "text",
    icon: <BankOutlined className="lib-status-icon lib-status-icon--primary" />,
    className: "small-squared-button",
    labelKey: "button_library.coopshares",
  },
  bankDetails: {
    type: "text",
    icon: (
      <CreditCardOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.bank_details",
  },
  coopsharesAlert: {
    type: "text",
    icon: <BankOutlined className="lib-status-icon lib-status-icon--error" />,
    className: "small-squared-button",
    labelKey: "button_library.coopshares_alert",
  },
  cancel: {
    type: "text",
    icon: <StopOutlined className="lib-status-icon lib-status-icon--error" />,
    className: "small-squared-button",
    labelKey: "button_library.cancel",
  },
  ok: {
    type: "text",
    icon: (
      <CheckCircleOutlined className="lib-status-icon lib-status-icon--success" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.ok",
  },
  not_ok: {
    type: "text",
    icon: (
      <ExclamationCircleOutlined className="lib-status-icon lib-status-icon--error" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.not_ok",
  },
  adminConfirmed: {
    type: "text",
    icon: (
      <CheckCircleOutlined className="lib-status-icon lib-status-icon--base" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.admin_confirmed",
    style: {
      backgroundColor: "var(--color-primary)",
      color: "white",
    },
  },
  adminPending: {
    type: "text",
    icon: (
      <ClockCircleOutlined className="lib-status-icon lib-status-icon--warning" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.admin_pending",
  },
  adminRejected: {
    type: "text",
    icon: (
      <CloseCircleOutlined className="lib-status-icon lib-status-icon--base" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.admin_rejected",
    style: {
      backgroundColor: "var(--color-error)",
      color: "white",
    },
  },
  userActive: {
    type: "text",
    icon: <UserOutlined className="lib-status-icon lib-status-icon--success" />,
    className: "small-squared-button",
    labelKey: "button_library.user_active",
  },
  userPendingApproval: {
    type: "text",
    icon: (
      <ClockCircleOutlined className="lib-status-icon lib-status-icon--warning" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.user_pending_approval",
  },
  userPendingInvitation: {
    type: "text",
    icon: (
      <MailOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.user_pending_invitation",
  },
  userPendingInvitationExpired: {
    type: "text",
    icon: <MailOutlined className="lib-status-icon lib-status-icon--error" />,
    className: "small-squared-button",
    labelKey: "button_library.user_pending_invitation_expired",
  },
  userInactive: {
    type: "text",
    icon: (
      <UserOutlined className="lib-status-icon lib-status-icon--tertiary" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.user_inactive",
  },
  userInvited: {
    type: "text",
    icon: <MailOutlined className="lib-status-icon lib-status-icon--warning" />,
    className: "small-squared-button",
    labelKey: "button_library.user_invited",
  },
  userNotInvited: {
    type: "text",
    icon: (
      <ExclamationCircleOutlined className="lib-status-icon lib-status-icon--warning" />
    ),
    className: "small-squared-button",
    labelKey: "button_library.user_not_invited",
  },
};

interface StatusButtonProps {
  variant: string;
  onClick?: () => void;
  tooltip?: string;
  disabled?: boolean;
  showTooltip?: boolean;
  [key: string]: unknown;
}

export const StatusButton = ({
  variant,
  onClick,
  tooltip,
  disabled = false,
  showTooltip = false,
  ...props
}: StatusButtonProps) => {
  const { t } = useTranslation();
  const config = BUTTON_CONFIGS[variant];
  if (!config) {
    console.warn(`Unknown status button variant: ${variant}`);
    return null;
  }

  // ``labelKey`` is not a Button prop — strip it before spreading. The default
  // label comes from the config's translated key; an explicit ``tooltip`` prop
  // (already localized by the caller) still wins.
  const { labelKey, ...buttonConfig } = config;
  const configLabel = t(labelKey);

  // These are icon-only buttons — give them an accessible name so screen
  // readers announce the action, not an empty button (the visible cue is the
  // hover tooltip, which SR/keyboard users don't get).
  const label = tooltip ?? configLabel;
  const button = (
    <Button
      {...buttonConfig}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      {...props}
    />
  );

  return showTooltip && (tooltip || configLabel) ? (
    <Tooltip title={tooltip || configLabel}>{button}</Tooltip>
  ) : (
    button
  );
};

interface LinkButtonProps {
  variant?: string;
  to: string;
  tooltip?: string;
  disabled?: boolean;
  showTooltip?: boolean;
  [key: string]: unknown;
}

export const LinkButton = ({
  variant = "view",
  to,
  tooltip,
  disabled = false,
  showTooltip = false,
  ...props
}: LinkButtonProps) => {
  const { t } = useTranslation();
  const config = BUTTON_CONFIGS[variant];
  if (!config) {
    console.warn(`Unknown link button variant: ${variant}`);
    return null;
  }

  const { labelKey, ...buttonConfig } = config;
  const configLabel = t(labelKey);

  // Icon-only button → give it an accessible name (see StatusButton).
  const label = tooltip ?? configLabel;
  const button = (
    <Link to={to}>
      <Button
        {...buttonConfig}
        disabled={disabled}
        aria-label={label}
        {...props}
      />
    </Link>
  );

  return showTooltip && (tooltip || configLabel) ? (
    <Tooltip title={tooltip || configLabel}>{button}</Tooltip>
  ) : (
    button
  );
};
