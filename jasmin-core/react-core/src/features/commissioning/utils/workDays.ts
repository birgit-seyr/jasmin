import type { SharesDeliveryDay } from "@shared/api/generated/models";

/** The work days a delivery day's shares take their harvest, packing, washing
 *  and cleaning from, each with its label key. */
export const WORK_DAY_LABELS = {
  default_harvesting_day: "configuration.default_harvesting_day",
  default_packing_day: "configuration.default_packing_day",
  default_washing_day: "configuration.default_washing_day",
  default_cleaning_day: "configuration.default_cleaning_day",
} as const;

export type WorkDayField = keyof typeof WORK_DAY_LABELS;

/** The work days a farm sets: washing and cleaning only where it shows them. */
export function shownWorkDayFields(
  showsWashing: boolean,
  showsCleaning: boolean,
): WorkDayField[] {
  return (Object.keys(WORK_DAY_LABELS) as WorkDayField[]).filter(
    (field) =>
      (showsWashing || field !== "default_washing_day") &&
      (showsCleaning || field !== "default_cleaning_day"),
  );
}

/** The label keys of the ``shownFields`` that ``day`` lacks. */
export function missingWorkDays(
  day: Pick<SharesDeliveryDay, WorkDayField>,
  shownFields: WorkDayField[],
): string[] {
  return shownFields
    .filter((field) => day[field] == null)
    .map((field) => WORK_DAY_LABELS[field]);
}
