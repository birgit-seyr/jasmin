import { createEnumOptionsHook } from "./internal/createEnumOptionsHook";
import type { TFunction } from "i18next";

const UNIT_OPTIONS = {
  KG: "KG",
  PCS: "PCS",
  BUNCH: "BUNCH",
} as const;

const labels: Record<keyof typeof UNIT_OPTIONS, string> = {
  KG: "commissioning.units.kg",
  PCS: "commissioning.units.pcs",
  BUNCH: "commissioning.units.bunch",
};

const { useEnumOptions, getLabelPure } = createEnumOptionsHook(
  UNIT_OPTIONS,
  (value, t) => t(labels[value]),
);

export const useUnitOptions = () => {
  const { options, getLabel } = useEnumOptions();
  return {
    UNIT_OPTIONS,
    unitOptions: options,
    getUnitLabel: getLabel,
  };
};

/** Pure function version – no hooks, safe for pdf() rendering */
export const getUnitLabelPure = (value: string, t: TFunction): string =>
  getLabelPure(value, t);

