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

export const useVegetableSizeOptions = () => {
  const { options, getLabel } = useEnumOptions();
  return {
    VEGETABLE_SIZE_OPTIONS,
    vegetableSizeOptions: options,
    getVegetableSizeLabel: getLabel,
  };
};

/** Pure function version – no hooks, safe for pdf() rendering */
export const getVegetableSizeLabelPure = (value: string, t: TFunction): string =>
  getLabelPure(value, t);

