import { useCallback } from "react";
import { useShareTypeVariationSizeOptions } from "./useShareTypeVariationSizeOptions";

// The raw size enum values the backend bakes into ``share_type_variation_string``
// (SizeOptions.choices). XS…XXL are identity-localized (label == code), so only
// HALF/FULL/ONE_SIZE visibly change — but we handle the whole set uniformly.
const SIZE_CODES = new Set([
  "XS",
  "S",
  "M",
  "L",
  "XL",
  "XXL",
  "HALF",
  "FULL",
  "ONE_SIZE",
]);

/**
 * Localize the size in a backend ``share_type_variation_string``.
 *
 * The backend composes it as ``"<share type name> - <SIZE>"`` with the RAW size
 * enum (e.g. ``"Gemüse - FULL"``), which ``getShareTypeVariationSizeLabel`` can
 * no longer reach once it's a single string — so the size shows as a code
 * ("FULL") while the edit dropdown shows the localized label ("GANZ"). This
 * hook swaps the trailing ``" - <SIZE>"`` token for its localized label,
 * yielding ``"Gemüse - GANZ"``. Strings without a recognized trailing size code
 * (e.g. a name that itself contains " - ") pass through unchanged.
 *
 * Use it at every place that DISPLAYS ``share_type_variation_string`` so the
 * read view matches the localized edit options.
 */
export function useVariationLabel() {
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  return useCallback(
    (variationString?: string | null): string => {
      if (!variationString) return "";
      const idx = variationString.lastIndexOf(" - ");
      if (idx === -1) return variationString;
      const size = variationString.slice(idx + 3);
      if (!SIZE_CODES.has(size)) return variationString;
      return `${variationString.slice(0, idx)} - ${getShareTypeVariationSizeLabel(size)}`;
    },
    [getShareTypeVariationSizeLabel],
  );
}
