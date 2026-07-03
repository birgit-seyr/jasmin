import { useCallback, useEffect, useMemo } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Select } from "antd";
import type { DefaultOptionType } from "antd/es/select";

export interface SelectorOption<V> {
  value: V;
  label: ReactNode;
}

export interface BaseEntitySelectorProps<V> {
  /** Currently selected value. */
  value: V | null | undefined;
  /** Update the selected value. */
  onValueChange: (value: V) => void;
  /** Optional secondary callback fired after onValueChange. */
  onChange?: ((value: V) => void) | null;

  options: SelectorOption<V>[];
  loading?: boolean;
  placeholder?: string;

  /** antd Select inline style. */
  style?: CSSProperties;
  /** antd Select className. Defaults to "bold-select week-selector-select". */
  className?: string;
  /** antd Select size. Defaults to "small". */
  size?: "small" | "middle" | "large";
  disabled?: boolean;

  /** Enable searchable dropdown. */
  showSearch?: boolean;
  filterOption?: (input: string, option?: DefaultOptionType) => boolean;
  optionFilterProp?: string;

  /**
   * If true, when no value is selected (or current value is no longer in
   * options) automatically pick the first option once loading finishes.
   * If `preserveSelection` is also set, only auto-pick when the current
   * value is missing from the options.
   */
  autoSelectFirst?: boolean;
  /** Keep the current selection if it still exists in options. */
  preserveSelection?: boolean;
}

const DEFAULT_FILTER_OPTION = (
  input: string,
  option?: DefaultOptionType,
): boolean =>
  String(option?.label ?? "")
    .toLowerCase()
    .includes(input.toLowerCase());

/**
 * Shared behavior for "fetch a list of entities, render an antd Select,
 * notify a setter + optional callback, optionally auto-select default".
 */
export default function BaseEntitySelector<V extends string | number | null>({
  value,
  onValueChange,
  onChange = null,
  options,
  loading = false,
  placeholder,
  style,
  className = "bold-select week-selector-select",
  size = "small",
  disabled = false,
  showSearch = false,
  filterOption,
  optionFilterProp,
  autoSelectFirst = false,
  preserveSelection = false,
}: BaseEntitySelectorProps<V>) {
  // Auto-select / preserve-selection logic
  useEffect(() => {
    if (loading || !options.length) return;
    if (!autoSelectFirst && !preserveSelection) return;

    const currentExists = options.some((o) => o.value === value);
    const isMissing = value === null || value === undefined || !currentExists;

    if (preserveSelection ? isMissing : autoSelectFirst && !value) {
      const first = options[0]?.value;
      if (first !== undefined) onValueChange(first);
    }
  }, [
    options,
    loading,
    value,
    onValueChange,
    autoSelectFirst,
    preserveSelection,
  ]);

  const handleChange = useCallback(
    (next: V) => {
      onValueChange(next);
      onChange?.(next);
    },
    [onValueChange, onChange],
  );

  const effectiveFilterOption = useMemo(() => {
    if (!showSearch) return undefined;
    return filterOption ?? DEFAULT_FILTER_OPTION;
  }, [showSearch, filterOption]);

  return (
    <Select
      value={value ?? undefined}
      style={style}
      className={className}
      size={size}
      onChange={handleChange}
      options={options as DefaultOptionType[]}
      placeholder={placeholder}
      loading={loading}
      disabled={disabled}
      showSearch={showSearch}
      filterOption={effectiveFilterOption}
      optionFilterProp={optionFilterProp}
    />
  );
}
