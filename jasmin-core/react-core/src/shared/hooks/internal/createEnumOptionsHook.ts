import type { TFunction } from "i18next";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export interface EnumOptionsHook<K extends string> {
  /** Translated, memoised `[ {value, label}, … ]` array. */
  options: Array<{ value: K; label: string }>;
  /** Lookup helper: returns the translated label for a given value, falling back to the value itself. */
  getLabel: (value: string) => string;
}

/**
 * Factory that builds the trio "constants + translated options + label getter"
 * used by the small enum-option hooks (sizes, units, share-variation sizes).
 *
 * Also exposes a "pure" label getter that takes its own `t` function — safe
 * to use outside React (e.g. inside `pdf()` rendering).
 */
export function createEnumOptionsHook<K extends string>(
  values: Record<K, K>,
  resolveLabel: (value: K, t: TFunction) => string,
  /** Optional override for the label getter (e.g. multi-value parsing). */
  labelLookup?: (value: string, options: Array<{ value: K; label: string }>) => string,
) {
  const keys = Object.values(values) as K[];

  const buildOptions = (t: TFunction) =>
    keys.map((value) => ({ value, label: resolveLabel(value, t) }));

  /** Pure (non-hook) helper. */
  const getLabelPure = (value: string, t: TFunction): string => {
    const opts = buildOptions(t);
    return labelLookup
      ? labelLookup(value, opts)
      : (opts.find((o) => o.value === value)?.label ?? value);
  };

  /** The React hook. */
  const useEnumOptions = (): EnumOptionsHook<K> => {
    const { t } = useTranslation();
    const options = useMemo(() => buildOptions(t), [t]);
    const getLabel = useMemo(
      () => (value: string) =>
        labelLookup
          ? labelLookup(value, options)
          : (options.find((o) => o.value === value)?.label ?? value),
      [options],
    );
    return { options, getLabel };
  };

  return { useEnumOptions, getLabelPure };
}
