import { Button } from "antd";
import type { ReactNode } from "react";

export interface IconActionButtonProps {
  icon: ReactNode;
  /** Tooltip AND accessible name — icon-only buttons need a label. */
  label: string;
  onClick: () => void;
  disabled?: boolean;
  /** Extra class(es) alongside the compact styling (e.g. "long-squared-button"). */
  className?: string;
  /** Optional icon colour — e.g. a status colour (pass a CSS var or value). */
  color?: string;
}

/**
 * Compact, icon-only text button for table-cell actions (delivery-station
 * settings, seller certificates, …). Stops row-click propagation, sets both a
 * tooltip and an aria-label from `label`, and uses the shared
 * `.btn-icon-compact` class instead of a per-call-site inline style.
 */
export default function IconActionButton({
  icon,
  label,
  onClick,
  disabled,
  className,
  color,
}: IconActionButtonProps) {
  return (
    <Button
      size="small"
      type="text"
      icon={icon}
      title={label}
      aria-label={label}
      disabled={disabled}
      className={className ? `btn-icon-compact ${className}` : "btn-icon-compact"}
      style={color ? { color } : undefined}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    />
  );
}
