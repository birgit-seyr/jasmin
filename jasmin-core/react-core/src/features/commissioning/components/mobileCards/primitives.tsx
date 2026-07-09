import { Flex, Tag } from "antd";
import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Shared building blocks for mobile-card variants used by EditableTable's
 * `renderMobileCard`. These exist to remove copy/paste between the various
 * `*MobileCard` components in this folder.
 *
 * Conventions match the existing CSS classes in
 * `components/tables/BasicEditableTable/MobileCardList.css`
 * (`mobile-card-item`, `mobile-card-content`, `mobile-card-title`, etc.) and
 * the global typography helpers (`text-hint`, `text-meta`, `text-muted-xs`,
 * `flex-baseline`, `text-secondary`).
 */

export const MOBILE_CARD_PLACEHOLDER = "\u2013"; // en-dash

interface MobileCardProps {
  onClick?: () => void;
  finalized?: boolean;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}

export function MobileCard({
  onClick,
  finalized,
  className,
  style,
  children,
}: MobileCardProps) {
  const classes = [
    "mobile-card-item",
    finalized ? "mobile-card-finalized" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    // role + tabIndex + onKeyDown are all set together when onClick is present
    // (and all absent otherwise), so this stays accessible whether clickable or not.
    <div
      className={classes}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      style={{
        cursor: onClick ? "pointer" : "default",
        alignItems: "stretch",
        position: "relative",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

interface MobileCardTitleProps {
  name: ReactNode;
  sizeLabel?: string;
  finalized?: boolean;
  /** Optional right-aligned content (e.g. amount, badge). */
  rightSlot?: ReactNode;
  /** Wrap the whole title row in a content wrapper. */
  wrap?: boolean;
}

export function MobileCardTitle({
  name,
  sizeLabel,
  finalized,
  rightSlot,
}: MobileCardTitleProps) {
  const { t } = useTranslation();
  return (
    <div
      className="mobile-card-title"
      style={rightSlot ? { justifyContent: "space-between" } : undefined}
    >
      <Flex align="center" gap={6} component="span">
        {/* A11Y-10: the finalized state is otherwise colour-only — role=img +
            aria-label exposes it to screen readers without any visual change. */}
        {finalized && (
          <span
            className="mobile-card-finalized-dot"
            role="img"
            aria-label={t("commissioning.finalized")}
          />
        )}
        {name}
        {sizeLabel && <span className="text-hint">{sizeLabel}</span>}
      </Flex>
      {rightSlot && <span style={{ whiteSpace: "nowrap" }}>{rightSlot}</span>}
    </div>
  );
}

/** Flex container for the standard "expected / actual / total" metric row. */
export function MobileCardMetricsRow({
  children,
  gap = 24,
}: {
  children: ReactNode;
  gap?: number;
}) {
  return (
    <Flex gap={gap} wrap style={{ marginTop: 6 }}>
      {children}
    </Flex>
  );
}

interface MobileCardMetricProps {
  label?: string;
  value: ReactNode;
  unit?: string;
  emphasis?: "primary" | "secondary";
  color?: string;
  minWidth?: number;
}

export function MobileCardMetric({
  label,
  value,
  unit,
  emphasis = "primary",
  color,
  minWidth,
}: MobileCardMetricProps) {
  const fontWeight = emphasis === "primary" ? 600 : 500;
  return (
    <div style={minWidth ? { minWidth, textAlign: "center" } : undefined}>
      {label && <div className="text-muted-xs">{label}</div>}
      <div className="flex-baseline">
        <span style={{ fontWeight, fontSize: "1.2em", color }}>{value}</span>
        {unit && <span className="text-secondary">{unit}</span>}
      </div>
    </div>
  );
}

export function MobileCardNote({ note }: { note?: string | null }) {
  if (!note) return null;
  return <div className="text-meta">{note}</div>;
}

export function MobileCardTags({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 4,
        marginTop: 6,
      }}
    >
      {tags.map((tag) => (
        <Tag key={tag} className="mobile-card-tag">
          {tag}
        </Tag>
      ))}
    </div>
  );
}

/** Wraps content with the standard `.mobile-card-content.flex-min` shell. */
export function MobileCardContent({ children }: { children: ReactNode }) {
  return <div className="mobile-card-content flex-min">{children}</div>;
}

/** Stop click propagation so an inner action button does not also trigger
 *  the card's onClick (used e.g. for the harvest confirm button). */
export function stopPropagation(e: MouseEvent) {
  e.stopPropagation();
}

/** Convenience helper used by several pages for the size label suffix. */
export function getSizeLabelOrEmpty(
  size: string | null | undefined,
  getVegetableSizeLabel: (size: string) => string,
): string {
  return size && size !== "M" ? getVegetableSizeLabel(size) : "";
}
