import { isValidElement } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Typography } from "antd";
import {
  ExclamationCircleOutlined,
  InfoCircleOutlined,
  WarningOutlined,
  CheckCircleOutlined,
} from "@ant-design/icons";

const { Text } = Typography;

interface PresetConfig {
  icon: ReactNode;
  backgroundColor: string;
  borderColor: string;
  iconColor: string;
}

interface ExplainerTextProps {
  children: ReactNode;
  icon?: ReactNode | string;
  title?: string;
  style?: CSSProperties;
  maxWidth?: string;
  marginTop?: string;
  backgroundColor?: string;
  borderColor?: string;
  type?: "warning" | "info" | "error" | "success";
}

const presets: Record<string, PresetConfig> = {
  warning: {
    icon: <ExclamationCircleOutlined />,
    backgroundColor: "var(--color-highlight)",
    borderColor: "#ffd591",
    iconColor: "#ffa800",
  },
  info: {
    icon: <InfoCircleOutlined />,
    backgroundColor: "var(--color-info-bg)",
    borderColor: "#91d5ff",
    iconColor: "var(--color-future-blue)",
  },
  error: {
    icon: <WarningOutlined />,
    backgroundColor: "#fff2f0",
    borderColor: "#ffccc7",
    iconColor: "var(--color-error)",
  },
  success: {
    icon: <CheckCircleOutlined />,
    backgroundColor: "var(--color-success-bg)",
    borderColor: "#b7eb8f",
    iconColor: "var(--color-success)",
  },
};

const ExplainerText = ({
  children,
  icon = "💡",
  title,
  style = {},
  maxWidth = "40em",
  marginTop = "2em",
  backgroundColor = "var(--color-bg-elevated)",
  borderColor = "var(--color-border-soft)",
  type,
}: ExplainerTextProps) => {
  const preset = type ? presets[type] : undefined;
  const finalIcon = preset?.icon || icon;
  const finalBackgroundColor = preset?.backgroundColor || backgroundColor;
  const finalBorderColor = preset?.borderColor || borderColor;
  const iconColor = preset?.iconColor || "var(--color-text-secondary)";

  return (
    <div
      style={{
        maxWidth,
        marginTop,
        padding: "1.25em",
        backgroundColor: finalBackgroundColor,
        borderRadius: "8px",
        border: `1px solid ${finalBorderColor}`,
        ...style,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5em",
          marginBottom: "0.5em",
        }}
      >
        <span style={{ color: iconColor, fontSize: "1em" }}>
          {isValidElement(finalIcon) ? finalIcon : finalIcon}
        </span>
        {title && (
          <Text
            strong
            style={{
              fontSize: "0.85em",
              color: "var(--color-text-secondary)",
              margin: 0,
            }}
          >
            {title}
          </Text>
        )}
      </div>
      <Text
        type="secondary"
        style={{
          fontSize: "0.9em",
          lineHeight: "1.6",
          margin: 0,
        }}
      >
        {children}
      </Text>
    </div>
  );
};

export default ExplainerText;
