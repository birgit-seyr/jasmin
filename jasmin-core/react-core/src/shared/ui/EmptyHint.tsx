import { Typography } from "antd";
import type { CSSProperties, ReactNode } from "react";

const { Text } = Typography;

interface EmptyHintProps {
  /** Already-translated placeholder message. */
  children: ReactNode;
  /** Extra styles merged onto the wrapper (e.g. taller padding for charts). */
  style?: CSSProperties;
}

/**
 * Subtle "no data" placeholder — a small, centered, muted line of text.
 * Deliberately icon-less: the replacement for AntD's `<Empty>`, whose large
 * illustration is too heavy for inline "nothing here yet" states.
 */
export default function EmptyHint({ children, style }: EmptyHintProps) {
  return (
    <div style={{ padding: "12px 0", textAlign: "center", ...style }}>
      <Text type="secondary">{children}</Text>
    </div>
  );
}
