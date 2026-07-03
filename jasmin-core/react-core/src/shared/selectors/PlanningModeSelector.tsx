import type { CSSProperties } from "react";
import { Radio, Card } from "antd";
import type { RadioChangeEvent } from "antd";
import { useTranslation } from "react-i18next";
import { ToolTipIcon } from "../ui";
import { getCSSVariable } from "@shared/utils/helpers";

interface PlanningModeSelectorProps {
  value: string;
  onChange?: (value: string) => void;
  style?: CSSProperties;
  size?: "small" | "default";
  disabled?: boolean;
  toursExist?: boolean;
  daysOk?: boolean;
  toursOk?: boolean;
}

const PlanningModeSelector = ({
  value,
  onChange,
  style = { width: "22em", marginBottom: "2em", marginTop: "2em" },
  size = "small",
  disabled = false,
  toursExist = false,
  daysOk = true,
  toursOk = true,
}: PlanningModeSelectorProps) => {
  const { t } = useTranslation();

  const primaryColor = getCSSVariable("--color-primary");

  const planningModes = [
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
    },
  ];

  const handleChange = (e: RadioChangeEvent) => {
    onChange?.(e.target.value);
  };

  return (
    <Card
      style={{
        ...style,
        boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
        borderRadius: "8px",
        marginTop: "0em",
      }}
      size={size}
      styles={{ body: { padding: "6px" } }}
    >
      <ToolTipIcon
        title={t("tooltip.planning_mode_tours_tooltip")}
        style={{
          position: "absolute",
          top: "8px",
          right: "8px",
          zIndex: 1,
        }}
      />
      <Radio.Group
        value={value}
        onChange={handleChange}
        className="w-full"
        disabled={disabled}
      >
        {planningModes.map((mode, index) => (
          // Mouse-only hover styling (border/background) over a keyboard-
          // accessible <Radio> — the Radio is the control; this wrapper just
          // restyles on pointer hover, so no keyboard handler is owed here.
          <div
            key={mode.value}
            style={{
              display: "flex",
              alignItems: "center",
              marginBottom: index === planningModes.length - 1 ? "0" : "6px",
              padding: "6px 8px",
              border:
                value === mode.value
                  ? `2px solid ${primaryColor}`
                  : "1px solid var(--color-border-subtle)",
              borderRadius: "6px",
              backgroundColor:
                value === mode.value
                  ? "#e6f7ff"
                  : mode.disabled
                    ? "var(--color-bg-elevated)"
                    : "var(--color-bg-base)",
              cursor: mode.disabled ? "not-allowed" : "pointer",
              transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
              opacity: mode.disabled ? 0.5 : 1,
              boxShadow:
                value === mode.value
                  ? "0 2px 8px rgba(24, 144, 255, 0.2)"
                  : "none",
            }}
            onMouseEnter={(e) => {
              if (!mode.disabled && value !== mode.value) {
                e.currentTarget.style.borderColor = `${primaryColor}`;
                e.currentTarget.style.backgroundColor = "#f0f9ff";
              }
            }}
            onMouseLeave={(e) => {
              if (!mode.disabled && value !== mode.value) {
                e.currentTarget.style.borderColor = "var(--color-border-subtle)";
                e.currentTarget.style.backgroundColor = "#ffffff";
              }
            }}
          >
            <Radio
              value={mode.value}
              style={{
                margin: 0,
                display: "flex",
                alignItems: "center",
                width: "100%",
              }}
              disabled={mode.disabled}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  marginLeft: "6px",
                  width: "100%",
                }}
              >
                <span
                  style={{
                    fontWeight: value === mode.value ? 600 : 500,
                    fontSize: "13px",
                    color: value === mode.value ? `${primaryColor}` : "var(--color-text-primary)",
                  }}
                >
                  {mode.label}
                </span>
              </div>
            </Radio>
          </div>
        ))}
      </Radio.Group>
    </Card>
  );
};

export default PlanningModeSelector;
