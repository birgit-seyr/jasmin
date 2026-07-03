import { createEnumOptionsHook } from "./internal/createEnumOptionsHook";
import type { TFunction } from "i18next";

const VEGETABLE_SIZE_OPTIONS = {
  S: "S",
  M: "M",
  L: "L",
} as const;

const labels: Record<keyof typeof VEGETABLE_SIZE_OPTIONS, string> = {
  S: "commissioning.small",
  M: "commissioning.medium",
  L: "commissioning.large",
};

const { useEnumOptions, getLabelPure } = createEnumOptionsHook(
  VEGETABLE_SIZE_OPTIONS,
  (value, t) => t(labels[value]),
);

export const useSizeOptions = () => {
  const { options, getLabel } = useEnumOptions();
  return {
    VEGETABLE_SIZE_OPTIONS,
    sizeOptions: options,
    getSizeLabel: getLabel,
  };
};

/** Pure function version – no hooks, safe for pdf() rendering */
export const getSizeLabelPure = (value: string, t: TFunction): string =>
  getLabelPure(value, t);

