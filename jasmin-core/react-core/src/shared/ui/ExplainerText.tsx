import type { CSSProperties, ReactNode } from "react";
import { Typography } from "antd";

const { Text } = Typography;

interface ExplainerTextProps {
  children: ReactNode;
  title?: string;
  style?: CSSProperties;
  maxWidth?: string;
  marginTop?: string;
}

/** Whether a body says nothing: no node, or only blank text. An explainer whose
 *  locale text is still an empty string is such a body. */
function isBlank(node: ReactNode): boolean {
  if (node == null || typeof node === "boolean") return true;
  if (typeof node === "string") return node.trim() === "";
  if (Array.isArray(node)) return node.every(isBlank);
  return false;
}

/** A soft panel that explains a page or one of its sections; nothing at all
 *  when there is no text to explain it with. */
const ExplainerText = ({
  children,
  title,
  style = {},
  maxWidth = "40em",
  marginTop = "2em",
}: ExplainerTextProps) =>
  isBlank(children) ? null : (
    <div className="explainer-text" style={{ maxWidth, marginTop, ...style }}>
      <div className="explainer-text__header">
        <span aria-hidden="true" className="explainer-text__icon">
          💡
        </span>
        {title && (
          <Text strong className="explainer-text__title">
            {title}
          </Text>
        )}
      </div>
      <Text type="secondary" className="explainer-text__body">
        {children}
      </Text>
    </div>
  );

export default ExplainerText;
