import type { CSSProperties, ReactNode } from "react";
import { Button, Tooltip } from "antd";
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
  tooltip?: string;
  style?: CSSProperties;
  danger?: boolean;
}

// Only variants actually referenced anywhere in the codebase are kept.
const BUTTON_CONFIGS: Record<string, ButtonConfig> = {
  view: {
    type: "text",
    size: "small",
    icon: <EyeOutlined className="lib-status-icon" />,
    tooltip: "View details",
    className: "small-squared-button",
  },
  logging: {
    type: "text",
    icon: (
      <HistoryOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    tooltip: "Activity Log",
  },
  emails: {
    type: "text",
    icon: (
      <MailOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    tooltip: "Sent emails",
  },
  coopshares: {
    type: "text",
    icon: <BankOutlined className="lib-status-icon lib-status-icon--primary" />,
    className: "small-squared-button",
    tooltip: "Coop shares",
  },
  bankDetails: {
    type: "text",
    icon: (
      <CreditCardOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    tooltip: "Edit bank details",
  },
  coopsharesAlert: {
    type: "text",
    icon: <BankOutlined className="lib-status-icon lib-status-icon--error" />,
    className: "small-squared-button",
    tooltip: "Coop shares — none on file",
  },
  cancel: {
    type: "text",
    icon: <StopOutlined className="lib-status-icon lib-status-icon--error" />,
    className: "small-squared-button",
    tooltip: "Cancel",
  },
  ok: {
    type: "text",
    icon: (
      <CheckCircleOutlined className="lib-status-icon lib-status-icon--success" />
    ),
    className: "small-squared-button",
    tooltip: "ok",
  },
  not_ok: {
    type: "text",
    icon: (
      <ExclamationCircleOutlined className="lib-status-icon lib-status-icon--error" />
    ),
    className: "small-squared-button",
    tooltip: "not ok",
  },
  adminConfirmed: {
    type: "text",
    icon: (
      <CheckCircleOutlined className="lib-status-icon lib-status-icon--base" />
    ),
    className: "small-squared-button",
    tooltip: "Admin confirmed",
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
    tooltip: "Admin confirmation pending",
  },
  adminRejected: {
    type: "text",
    icon: (
      <CloseCircleOutlined className="lib-status-icon lib-status-icon--base" />
    ),
    className: "small-squared-button",
    tooltip: "Application rejected",
    style: {
      backgroundColor: "var(--color-error)",
      color: "white",
    },
  },
  userActive: {
    type: "text",
    icon: <UserOutlined className="lib-status-icon lib-status-icon--success" />,
    className: "small-squared-button",
    tooltip: "User account active",
  },
  userPendingApproval: {
    type: "text",
    icon: (
      <ClockCircleOutlined className="lib-status-icon lib-status-icon--warning" />
    ),
    className: "small-squared-button",
    tooltip: "Pending admin approval",
  },
  userPendingInvitation: {
    type: "text",
    icon: (
      <MailOutlined className="lib-status-icon lib-status-icon--future-blue" />
    ),
    className: "small-squared-button",
    tooltip: "Invitation sent",
  },
  userPendingInvitationExpired: {
    type: "text",
    icon: <MailOutlined className="lib-status-icon lib-status-icon--error" />,
    className: "small-squared-button",
    tooltip: "Invitation expired",
  },
  userInactive: {
    type: "text",
    icon: (
      <UserOutlined className="lib-status-icon lib-status-icon--tertiary" />
    ),
    className: "small-squared-button",
    tooltip: "User account inactive",
  },
  userInvited: {
    type: "text",
    icon: <MailOutlined className="lib-status-icon lib-status-icon--warning" />,
    className: "small-squared-button",
    tooltip: "Invitation sent",
  },
  userNotInvited: {
    type: "text",
    icon: (
      <ExclamationCircleOutlined className="lib-status-icon lib-status-icon--warning" />
    ),
    className: "small-squared-button",
    tooltip: "No invitation sent",
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
  const config = BUTTON_CONFIGS[variant];
  if (!config) {
    console.warn(`Unknown status button variant: ${variant}`);
    return null;
  }

  // These are icon-only buttons — give them an accessible name so screen
  // readers announce the action, not an empty button (the visible cue is the
  // hover tooltip, which SR/keyboard users don't get).
  const label = tooltip ?? config.tooltip;
  const button = (
    <Button
      {...config}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      {...props}
    />
  );

  return showTooltip && (tooltip || config.tooltip) ? (
    <Tooltip title={tooltip || config.tooltip}>{button}</Tooltip>
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
  const config = BUTTON_CONFIGS[variant];
  if (!config) {
    console.warn(`Unknown link button variant: ${variant}`);
    return null;
  }

  // Icon-only button → give it an accessible name (see StatusButton).
  const label = tooltip ?? config.tooltip;
  const button = (
    <Link to={to}>
      <Button {...config} disabled={disabled} aria-label={label} {...props} />
    </Link>
  );

  return showTooltip && (tooltip || config.tooltip) ? (
    <Tooltip title={tooltip || config.tooltip}>{button}</Tooltip>
  ) : (
    button
  );
};
