import type { CSSProperties } from "react";
import { Tooltip } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";

interface ToolTipIconProps {
  title?: string;
  fallbackText?: string;
  style?: CSSProperties;
  iconStyle?: CSSProperties;
  className?: string;
}

const ToolTipIcon = ({
  title,
  fallbackText = "Additional information",
  style = {},
  iconStyle = {},
  className,
}: ToolTipIconProps) => {
  const defaultIconStyle: CSSProperties = {
    marginLeft: 4,
    color: "var(--color-future-blue)",
    cursor: "pointer",
    verticalAlign: "super",
    fontSize: "0.8em",
    ...iconStyle,
  };

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
        className={className}
        style={{ ...defaultIconStyle, ...style }}
        tabIndex={0}
        role="img"
        aria-label={label}
      />
    </Tooltip>
  );
};

export default ToolTipIcon;
