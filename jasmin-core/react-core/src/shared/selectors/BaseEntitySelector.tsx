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
  /** Accessible name forwarded as aria-label. Defaults to placeholder. */
  ariaLabel?: string;

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
  /**
   * With `preserveSelection`: the value the pick becomes once the list has
   * loaded empty, so no pick from an earlier list stays shown. Left unset, an
   * empty list keeps the pick — the only choice for a value type without an
   * empty value.
   */
  emptyValue?: V;
}

// AntD Select treats a `null` value as "nothing picked" and shows the
// placeholder, so a `null` option (an "all" entry) goes through the Select
// under this stand-in value instead.
const NULL_OPTION_VALUE = "__base-entity-selector-null__";

const toSelectValue = <V extends string | number | null>(
  value: V,
): string | number => (value === null ? NULL_OPTION_VALUE : value);

const matchesOptionLabel = (
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
  ariaLabel,
  style,
  className = "bold-select week-selector-select",
  size = "small",
  disabled = false,
  showSearch = false,
  filterOption,
  optionFilterProp,
  autoSelectFirst = false,
  preserveSelection = false,
  emptyValue,
}: BaseEntitySelectorProps<V>) {
  // Auto-select / preserve-selection logic
  useEffect(() => {
    if (loading) return;
    if (!options.length) {
      if (preserveSelection && emptyValue !== undefined && value !== emptyValue) {
        onValueChange(emptyValue);
      }
      return;
    }
    if (!autoSelectFirst && !preserveSelection) return;

    const currentExists = options.some((o) => o.value === value);
    const isMissing = value === null || value === undefined || !currentExists;

    if (preserveSelection ? isMissing : autoSelectFirst && !value) {
      onValueChange(options[0].value);
    }
  }, [
    options,
    loading,
    value,
    onValueChange,
    autoSelectFirst,
    preserveSelection,
    emptyValue,
  ]);

  const selectOptions = useMemo<DefaultOptionType[]>(
    () =>
      options.map((option) => ({
        value: toSelectValue(option.value),
        label: option.label,
      })),
    [options],
  );

  const selectValue =
    value === null && options.some((option) => option.value === null)
      ? NULL_OPTION_VALUE
      : (value ?? undefined);

  const handleChange = useCallback(
    (next: string | number) => {
      const picked = options.find(
        (option) => toSelectValue(option.value) === next,
      );
      if (!picked) return;
      onValueChange(picked.value);
      onChange?.(picked.value);
    },
    [options, onValueChange, onChange],
  );

  const effectiveFilterOption = useMemo(() => {
    if (!showSearch) return undefined;
    return filterOption ?? matchesOptionLabel;
  }, [showSearch, filterOption]);

  return (
    <Select<string | number>
      value={selectValue}
      style={style}
      className={className}
      size={size}
      onChange={handleChange}
      options={selectOptions}
      placeholder={placeholder}
      aria-label={ariaLabel ?? placeholder}
      loading={loading}
      disabled={disabled}
      showSearch={showSearch}
      filterOption={effectiveFilterOption}
      optionFilterProp={optionFilterProp}
    />
  );
}
