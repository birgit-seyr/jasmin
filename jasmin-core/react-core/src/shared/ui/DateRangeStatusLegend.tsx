import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";

interface StatusConfig {
  color: string;
  labelKey: string;
}

const DEFAULT_STATUS_CONFIG: Record<string, StatusConfig> = {
  active: {
    color: "var(--color-success)",
    labelKey: "common.active",
  },
  future: {
    color: "var(--color-payments)",
    labelKey: "common.future",
  },
  inactive: {
    color: "var(--color-border)",
    labelKey: "common.inactive",
  },
};

interface DateRangeStatusLegendProps {
  statusConfig?: Record<string, StatusConfig>;
  style?: CSSProperties;
}

export default function DateRangeStatusLegend({
  statusConfig = DEFAULT_STATUS_CONFIG,
  style = {},
}: DateRangeStatusLegendProps) {
  const { t } = useTranslation();

  return (
    <div
      style={{
        display: "flex",
        gap: "16px",
        marginTop: "8px",
        fontSize: "11px",
        color: "var(--color-text-muted)",
        ...style,
      }}
    >
      {Object.entries(statusConfig).map(([key, config]) => (
        <span key={key} className="flex-center-y" style={{ gap: "4px" }}>
          <span
            style={{
              width: "10px",
              height: "10px",
              backgroundColor: config.color,
              borderRadius: "2px",
              display: "inline-block",
            }}
          />
          {t(config.labelKey)}
        </span>
      ))}
    </div>
  );
}
