import type { CSSProperties, ReactNode } from "react";
import { ExclamationCircleOutlined } from "@ant-design/icons";

interface PastWarningMessageProps {
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
  width?: string;
  [key: string]: unknown;
}

const PastWarningMessage = ({
  children,
  style = {},
  className = "",
  width = "40em",
  ...props
}: PastWarningMessageProps) => {
  return (
    <div
      className={`past-warning-message ${className}`}
      style={{
        ...(width && { width }),
        ...style,
      }}
      {...props}
    >
      <ExclamationCircleOutlined style={{ color: "var(--color-warning)" }} />
      <span>{children}</span>
    </div>
  );
};

export default PastWarningMessage;
