import {
  Checkbox,
  DatePicker,
  Input,
  InputNumber,
  Select,
  Typography,
} from "antd";
import dayjs from "dayjs";
import type { ComponentType } from "react";
import { ReactNode } from "react";
import { blockNonNumericKeys } from "@shared/utils/numberFormat";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { RemittanceTemplateInput } from "./RemittanceTemplateInput";

const { Text } = Typography;
const { Option } = Select;
const { TextArea } = Input;

type SettingType =
  | "checkbox"
  | "input"
  | "richtext"
  | "textarea"
  | "number"
  | "select"
  | "date"
  | "checkbox_with_pricing"
  | "remittance_template"
  | "tiers";

interface SelectOption {
  value: string | number;
  label: string;
  /** Render the option greyed-out and unselectable (kept visible on purpose,
   *  e.g. a strategy that's temporarily withdrawn but should still be seen). */
  disabled?: boolean;
}

export interface SettingsCategory {
  category: string;
  title?: string;
  description?: string;
  settings: SettingConfig[];
}

export interface SettingConfig {
  key: string;
  label: string;
  type: SettingType | string;
  defaultValue?: unknown;
  required?: boolean;
  disabled?: boolean;
  rows?: number;
  min?: number;
  max?: number;
  /** ``number`` fields only: spinner step + decimal precision (e.g. step 1 /
   * precision 0 for whole-unit integer settings). */
  step?: number;
  precision?: number;
  options?: SelectOption[];
  description?: string;
  shareType?: string;
  maxLength?: number;
  suffix?: string;
  maxLines?: number | null;
  maxCharacters?: number | null;
  maxCharsPerLine?: number | null;
  placeholderKey?: string;
  disabledTooltip?: string;
  /**
   * Show this setting only when the predicate returns true. Receives a
   * ``getSettingValue(key, defaultValue?)`` helper bound to the
   * currently-edited (unsaved) tenant settings so dependent rows
   * react to checkbox flips immediately, without waiting for an API
   * save. Omit for unconditionally-visible settings.
   *
   * Example: hide the "number of jokers" input until "uses_jokers"
   * is on:
   *
   *   { key: "amount_of_jokers", ..., visibleIf: (getValue) =>
   *       Boolean(getValue("uses_jokers", true)) }
   */
  visibleIf?: (
    getSettingValue: (key: string, defaultValue?: unknown) => unknown,
  ) => boolean;
  /**
   * Restrict selectable dates on ``type: "date"`` settings. Same
   * shape as Ant Design's ``DatePicker.disabledDate`` — return
   * ``true`` to disable a candidate date. Use for "must be a
   * Sunday" / "must be a Monday" / future-only style constraints.
   * No-op for non-date settings.
   */
  disabledDate?: (current: dayjs.Dayjs) => boolean;
  /**
   * Inline validator for ``type: "input"`` settings. Returns a
   * human-readable error message when the value is invalid, or
   * ``null`` when valid. The renderer skips it on empty values so
   * the office isn't shown a red error against a freshly-loaded
   * blank field. Use for format checks like IBAN / phone / postcode
   * where the backend would also reject the value at save time.
   */
  validate?: (value: string) => string | null;
}

interface RenderOptions {
  /** Tenant decimal separator (from useNumberFormat) for ``number`` inputs —
   * so the input shows/accepts the tenant's separator (e.g. ``.`` → 40.00) and
   * rejects everything else. Defaults to ``.``. */
  decimalChar?: string;
  onConfigurePrice?: (shareType: string, label: string) => void;
  renderPriceButton?: ComponentType<{
    shareType: string;
    label: string;
    onConfigurePrice: (shareType: string, label: string) => void;
  }>;
}

export const SettingsRenderer = {
  // Render input based on type

  renderInput: (
    setting: SettingConfig,
    value: unknown,
    onChange: (value: unknown) => void,
    options: RenderOptions = {},
  ): ReactNode => {
    switch (setting.type) {
      case "checkbox":
        return (
          <span style={{ display: "inline-flex", alignItems: "center" }}>
            <Checkbox
              checked={value as boolean}
              onChange={(e) => onChange(e.target.checked)}
              disabled={setting.disabled}
            >
              {setting.label}
            </Checkbox>
            {setting.disabled && setting.disabledTooltip && (
              <ToolTipIcon title={setting.disabledTooltip} />
            )}
          </span>
        );

      case "input": {
        // Lazy validation: only run ``setting.validate`` once a value
        // exists AND is non-empty. Stops the office from seeing red
        // errors against an empty field they haven't filled in yet.
        const validationError =
          setting.validate && value
            ? setting.validate(String(value))
            : null;
        return (
          <div>
            <Text strong>
              {setting.label}
              {setting.required && <span style={{ color: "var(--color-error)" }}> *</span>}
            </Text>
            <Input
              value={value as string}
              onChange={(e) => onChange(e.target.value)}
              placeholder={setting.defaultValue?.toString()}
              style={{ marginTop: 4 }}
              required={setting.required}
              disabled={setting.disabled}
              maxLength={setting.maxLength}
              status={validationError ? "error" : undefined}
            />
            {validationError && (
              <div
                style={{
                  fontSize: "0.85em",
                  color: "var(--color-error, #c0392b)",
                  marginTop: 2,
                }}
              >
                {validationError}
              </div>
            )}
          </div>
        );
      }

      case "remittance_template":
        return (
          <RemittanceTemplateInput
            setting={setting}
            value={(value as string) ?? ""}
            onChange={(v) => onChange(v)}
          />
        );

      case "richtext":
        // Handled separately in the component
        return null;

      case "textarea":
        return (
          <div>
            <Text strong>{setting.label}</Text>
            <TextArea
              value={value as string}
              onChange={(e) => onChange(e.target.value)}
              placeholder={setting.defaultValue?.toString()}
              style={{ marginTop: 4 }}
              rows={setting.rows || 3}
              disabled={setting.disabled}
            />
          </div>
        );

      case "number":
        return (
          <div>
            <Text strong>{setting.label}</Text>
            <InputNumber
              value={value as number}
              onChange={onChange}
              placeholder={setting.defaultValue?.toString()}
              style={{ width: "100%", marginTop: 4 }}
              min={setting.min}
              max={setting.max}
              // Default to whole-number entry (reject "100,4" / stray chars);
              // decimal fields (tax rates, percentages) opt in via `precision`.
              // ``decimalSeparator`` is the tenant's separator so the field
              // shows e.g. 40.00 (not 40,00) and rejects any other character.
              step={setting.step ?? 1}
              precision={setting.precision ?? 0}
              decimalSeparator={options.decimalChar ?? "."}
              onKeyDown={blockNonNumericKeys({
                allowDecimal: (setting.precision ?? 0) > 0,
                decimalChar: options.decimalChar ?? ".",
                allowNegative: (setting.min ?? 0) < 0,
              })}
              disabled={setting.disabled}
            />
          </div>
        );

      case "select":
        return (
          <div>
            <Text strong>{setting.label}</Text>
            <Select
              value={value as string | number}
              onChange={onChange}
              style={{ width: "100%", marginTop: 4 }}
              disabled={setting.disabled}
            >
              {setting.options?.map((option) => (
                <Option
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                >
                  {option.label}
                </Option>
              ))}
            </Select>
          </div>
        );

      case "date":
        return (
          <div>
            <Text strong>{setting.label}</Text>
            <DatePicker
              value={value ? dayjs(value as string) : null}
              onChange={(date) =>
                onChange(date ? date.format("YYYY-MM-DD") : null)
              }
              style={{ width: "100%", marginTop: 4 }}
              placeholder={setting.defaultValue as string}
              disabled={setting.disabled}
              disabledDate={setting.disabledDate}
            />
          </div>
        );

      case "checkbox_with_pricing":
        return (
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "12px",
              }}
            >
              <Checkbox
                checked={value as boolean}
                onChange={(e) => onChange(e.target.checked)}
                disabled={setting.disabled}
              >
                <strong>{setting.label}</strong>
              </Checkbox>
              {!!value &&
                options.onConfigurePrice &&
                options.renderPriceButton && (
                  <options.renderPriceButton
                    shareType={setting.shareType!}
                    label={setting.label}
                    onConfigurePrice={options.onConfigurePrice}
                  />
                )}
            </div>
          </div>
        );

      default:
        return null;
    }
  },

  // Get nested value helper
  getNestedValue: (
    obj: Record<string, unknown>,
    path: string,
    defaultValue?: unknown,
  ): unknown => {
    const keys = path.split(".");
    let value: unknown = obj;

    for (const k of keys) {
      value = (value as Record<string, unknown>)?.[k];
    }

    return value !== undefined ? value : defaultValue;
  },

  // Set nested value helper
  setNestedValue: (
    obj: Record<string, unknown>,
    path: string,
    value: unknown,
  ): Record<string, unknown> => {
    const newObj = { ...obj };
    const keys = path.split(".");

    if (keys.length === 1) {
      newObj[keys[0]] = value;
    } else if (keys.length === 2) {
      if (!newObj[keys[0]]) newObj[keys[0]] = {};
      (newObj[keys[0]] as Record<string, unknown>)[keys[1]] = value;
    }

    return newObj;
  },

  // Get column span based on setting type
  getColumnSpan: (setting: SettingConfig): number => {
    const fullWidthTypes = [
      "number",
      "date",
      "select",
      "input",
      "textarea",
      "remittance_template",
    ];
    const halfWidthTypes = ["checkbox", "checkbox_with_pricing"];

    if (fullWidthTypes.includes(setting.type)) {
      return 24;
    }
    if (halfWidthTypes.includes(setting.type)) {
      return 12;
    }
    return 24; // default
  },

  // Render a small secondary description below a setting
  renderDescription: (setting: SettingConfig): ReactNode => {
    if (!setting.description) return null;
    return (
      <div
        style={{
          marginTop: "4px",
          marginLeft: setting.type === "checkbox" ? "24px" : "0",
        }}
      >
        <Text type="secondary" style={{ fontSize: "12px" }}>
          {setting.description}
        </Text>
      </div>
    );
  },
};
