import { Switch } from "antd";
import { EyeInvisibleOutlined, EyeOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";
import { useId } from "react";
import ToolTipIcon from "./ToolTipIcon";

export interface LabeledSwitchProps {
  value: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  /** If true, render `EyeOutlined` / `EyeInvisibleOutlined` inside the switch. */
  withEyeIcons?: boolean;
  /** Optional tooltip rendered next to the label via `ToolTipIcon`. */
  tooltip?: string;
  size?: "default" | "small";
  disabled?: boolean;
  loading?: boolean;
  id?: string;
  /** Spacing between switch and label. */
  gap?: number | string;
}

export default function LabeledSwitch({
  value,
  onChange,
  label,
  withEyeIcons = false,
  tooltip,
  size,
  disabled,
  loading,
  id,
  gap = 8,
}: LabeledSwitchProps) {
  const generatedId = useId();
  const switchId = id ?? generatedId;

  return (
    <div className="flex-center-y" style={{ gap }}>
      <Switch
        id={switchId}
        checked={value}
        onChange={onChange}
        size={size}
        disabled={disabled}
        loading={loading}
        checkedChildren={withEyeIcons ? <EyeOutlined /> : undefined}
        unCheckedChildren={withEyeIcons ? <EyeInvisibleOutlined /> : undefined}
      />
      <label htmlFor={switchId} style={{ cursor: disabled ? "not-allowed" : "pointer" }}>
        {label}
        {tooltip && <ToolTipIcon title={tooltip} />}
      </label>
    </div>
  );
}
