import type { CSSProperties } from "react";
import { Button, Space } from "antd";
import { useTranslation } from "react-i18next";
import { ToolTipIcon } from "../ui";

interface PlanningModeSelectorProps {
  value: string;
  onChange?: (value: string) => void;
  style?: CSSProperties;
  size?: "small" | "middle" | "large";
  disabled?: boolean;
  toursExist?: boolean;
  daysOk?: boolean;
  toursOk?: boolean;
}

/**
 * Planning granularity picker — "plan by days / tours / distribution stations".
 * A connected button group (primary = selected, default = not) matching the
 * "separate days / combined view" toggle it sits above, so the two read as one
 * consistent control block. The tooltip flags that too-granular data can rule
 * out day planning.
 */
const PlanningModeSelector = ({
  value,
  onChange,
  style,
  size = "middle",
  disabled = false,
  toursExist = false,
  daysOk = true,
  toursOk = true,
}: PlanningModeSelectorProps) => {
  const { t } = useTranslation();

  const options = [
    {
      value: "basic",
      label: t("commissioning.planning_mode_basic"),
      disabled: !daysOk,
    },
    {
      value: "tours",
      label: t("commissioning.planning_mode_tours"),
      disabled: !toursOk || !toursExist,
    },
    {
      value: "stations",
      label: t("commissioning.planning_mode_stations"),
      disabled: false,
    },
  ];

  return (
    <Space size={6} align="center" style={style}>
      <Space.Compact>
        {options.map((opt) => (
          <Button
            key={opt.value}
            size={size}
            // Selection is otherwise conveyed only by the primary-vs-default
            // styling; aria-pressed exposes it to assistive tech.
            aria-pressed={value === opt.value}
            type={value === opt.value ? "primary" : "default"}
            disabled={disabled || opt.disabled}
            onClick={() => onChange?.(opt.value)}
          >
            {opt.label}
          </Button>
        ))}
      </Space.Compact>
      <ToolTipIcon title={t("tooltip.planning_mode_tours_tooltip")} />
    </Space>
  );
};

export default PlanningModeSelector;
