import {
  DefaultPlantingModeEnum,
  FertilizerRequirementEnum,
} from "@shared/api/generated/models";
import { createEnumOptionsHook } from "@shared/hooks/internal/createEnumOptionsHook";

// Planting mode (PLANTING / SOWING) — reuses the same enum-options factory as
// the shared unit/size hooks, driven by the generated enum const so the option
// set stays in sync with the backend choices.
const plantingMode = createEnumOptionsHook(
  DefaultPlantingModeEnum,
  (value, t) => t(`cultivation.planting_mode_${value.toLowerCase()}`),
);
export const usePlantingModeOptions = plantingMode.useEnumOptions;
export const getPlantingModeLabelPure = plantingMode.getLabelPure;

// Fertilizer requirement (WEAK / MIDDLE / STRONG).
const fertilizer = createEnumOptionsHook(
  FertilizerRequirementEnum,
  (value, t) => t(`cultivation.fertilizer_${value.toLowerCase()}`),
);
export const useFertilizerOptions = fertilizer.useEnumOptions;
export const getFertilizerLabelPure = fertilizer.getLabelPure;
