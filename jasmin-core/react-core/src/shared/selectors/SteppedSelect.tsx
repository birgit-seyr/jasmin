import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Divider, Select, Space } from "antd";
import type { SelectProps } from "antd";
import type { CSSProperties, ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * The shared "prev button · select · next button" arrow-navigation shell used
 * by every date stepper (Year / Week / Month / Day / SharesDeliveryDay). The
 * entity selectors were already collapsed onto ``BaseEntitySelector``; this is
 * the equivalent for the arrow-nav ones.
 *
 * Typing mirrors AntD's own loose ``Select`` surface (``value`` / ``onChange`` /
 * ``options`` picked straight from ``SelectProps``) so the existing per-selector
 * handlers pass through unchanged. Pass ``children`` (``<Option>`` elements)
 * INSTEAD of ``options`` when leaves need per-option classNames, as Day and
 * SharesDeliveryDay do.
 */
export interface SteppedSelectProps
  extends Pick<
    SelectProps,
    "value" | "onChange" | "options" | "loading" | "placeholder"
  > {
  onPrev: () => void;
  onNext: () => void;
  canGoPrev: boolean;
  canGoNext: boolean;
  /** ``<Option>`` children; use INSTEAD of ``options`` for per-option styling. */
  children?: ReactNode;
  selectStyle?: CSSProperties;
  selectAriaLabel?: string;
  /** Defaults to the shared week-selector select styling; override for
   *  month-selector-* etc. */
  selectClassName?: string;
  /** Defaults to the shared week-selector button styling; override for
   *  month-selector-* etc. */
  buttonClassName?: string;
  /** Render a leading vertical divider before the prev button (Week / Day /
   *  SharesDeliveryDay steppers do; Year / Month don't). */
  showDivider?: boolean;
  size?: "small" | "middle" | "large";
  prevAriaLabel?: string;
  nextAriaLabel?: string;
}

const SteppedSelect = ({
  value,
  onChange,
  options,
  loading,
  placeholder,
  onPrev,
  onNext,
  canGoPrev,
  canGoNext,
  children,
  selectStyle,
  selectAriaLabel,
  selectClassName = "bold-select week-selector-select",
  buttonClassName = "week-selector-small-buttons",
  showDivider = false,
  size = "small",
  prevAriaLabel,
  nextAriaLabel,
}: SteppedSelectProps) => {
  const { t } = useTranslation();

  return (
    <Space>
      {showDivider ? <Divider type="vertical" /> : null}
      <Button
        size={size}
        icon={<LeftOutlined />}
        onClick={onPrev}
        className={buttonClassName}
        disabled={!canGoPrev}
        aria-label={prevAriaLabel ?? t("common.previous")}
      />
      <Select
        value={value}
        onChange={onChange}
        options={children ? undefined : options}
        style={selectStyle}
        size={size}
        className={selectClassName}
        aria-label={selectAriaLabel}
        placeholder={placeholder}
        loading={loading}
      >
        {children}
      </Select>
      <Button
        size={size}
        icon={<RightOutlined />}
        onClick={onNext}
        className={buttonClassName}
        disabled={!canGoNext}
        aria-label={nextAriaLabel ?? t("common.next")}
      />
    </Space>
  );
};

export default SteppedSelect;
