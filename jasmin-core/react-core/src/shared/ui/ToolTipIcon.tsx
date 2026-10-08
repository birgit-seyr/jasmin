import type { CSSProperties } from "react";
import { Tooltip } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";

interface ToolTipIconProps {
  title?: string;
  fallbackText?: string;
  style?: CSSProperties;
  className?: string;
}

const ToolTipIcon = ({
  title,
  fallbackText = "Additional information",
  style,
  className,
}: ToolTipIconProps) => {
  const label = title || fallbackText;

  return (
    // ``trigger`` includes "focus" + the icon is focusable (tabIndex 0) so a
    // keyboard-only user can open the tooltip; ``aria-label`` gives the icon a
    // meaningful name instead of AntD's default "info-circle".
    <Tooltip
      title={label}
      trigger={["hover", "focus"]}
      classNames={{ root: "custom-tooltip" }}
    >
      <InfoCircleOutlined
        className={className ? `tooltip-icon ${className}` : "tooltip-icon"}
        style={style}
        tabIndex={0}
        role="img"
        aria-label={label}
      />
    </Tooltip>
  );
};

export default ToolTipIcon;
