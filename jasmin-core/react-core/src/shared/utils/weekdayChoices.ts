import type { TFunction } from "i18next";

export interface WeekdayChoice {
  value: number;
  label: string;
}

/**
 * Monday..Saturday (``value`` 0–5) labelled with the short acronym keys —
 * shared by every weekday picker / renderer so adding Sunday (value 6) or
 * renaming an acronym key is a one-file change instead of editing four call
 * sites in lockstep. Takes ``t`` so it imports nothing feature-side; wrap the
 * call in ``useMemo(() => getWeekdayChoices(t), [t])`` at the call site.
 */
export function getWeekdayChoices(t: TFunction): WeekdayChoice[] {
  return [
    { value: 0, label: t("configuration.acronym_monday") },
    { value: 1, label: t("configuration.acronym_tuesday") },
    { value: 2, label: t("configuration.acronym_wednesday") },
    { value: 3, label: t("configuration.acronym_thursday") },
    { value: 4, label: t("configuration.acronym_friday") },
    { value: 5, label: t("configuration.acronym_saturday") },
  ];
}
