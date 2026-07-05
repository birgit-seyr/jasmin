import type { CSSProperties } from "react";
import { Tooltip } from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";

interface ToolTipIconProps {
  title?: string;
  fallbackText?: string;
  style?: CSSProperties;
  iconStyle?: CSSProperties;
}

const ToolTipIcon = ({
  title,
  fallbackText = "Additional information",
  style = {},
  iconStyle = {},
}: ToolTipIconProps) => {
  const defaultIconStyle: CSSProperties = {
    marginLeft: 4,
    color: "var(--color-future-blue)",
    cursor: "pointer",
    verticalAlign: "super",
    fontSize: "0.8em",
    ...iconStyle,
  };

  return (
    <Tooltip
      title={title || fallbackText}
      classNames={{ root: "custom-tooltip" }}
    >
      <InfoCircleOutlined style={{ ...defaultIconStyle, ...style }} />
    </Tooltip>
  );
};

export default ToolTipIcon;
