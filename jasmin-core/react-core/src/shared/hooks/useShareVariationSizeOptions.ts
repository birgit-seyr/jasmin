import { createEnumOptionsHook } from "./internal/createEnumOptionsHook";

const SHARE_VARIATION_SIZE_OPTIONS = {
  XS: "XS",
  S: "S",
  M: "M",
  L: "L",
  XL: "XL",
  XXL: "XXL",
  HALF: "HALF",
  FULL: "FULL",
  ONE_SIZE: "ONE_SIZE",
} as const;

const labels: Record<keyof typeof SHARE_VARIATION_SIZE_OPTIONS, string> = {
  XS: "commissioning.XS",
  S: "commissioning.S",
  M: "commissioning.M",
  L: "commissioning.L",
  XL: "commissioning.XL",
  XXL: "commissioning.XXL",
  HALF: "commissioning.HALF",
  FULL: "commissioning.FULL",
  ONE_SIZE: "commissioning.ONE_SIZE",
};

const { useEnumOptions } = createEnumOptionsHook(
  SHARE_VARIATION_SIZE_OPTIONS,
  (value, t) => t(labels[value]),
  // Multi-value lookup: split on comma, translate each, rejoin.
  (value, opts) =>
    !value
      ? ""
      : value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
          .map((s) => opts.find((o) => o.value === s)?.label ?? s)
          .join(", "),
);

export const useShareVariationSizeOptions = () => {
  const { options, getLabel } = useEnumOptions();
  return {
    SHARE_VARIATION_SIZE_OPTIONS,
    shareVariationSizeOptions: options,
    getShareVariationSizeLabel: getLabel,
  };
};

