export const getDayName = (
  dayIndex: number | null,
  t: (key: string) => string,
): string => {
  const dayNames = [
    t("commissioning.weekdaysBIG.0"),
    t("commissioning.weekdaysBIG.1"),
    t("commissioning.weekdaysBIG.2"),
    t("commissioning.weekdaysBIG.3"),
    t("commissioning.weekdaysBIG.4"),
    t("commissioning.weekdaysBIG.5"),
    t("commissioning.weekdaysBIG.6"),
  ];

  const name = dayIndex == null ? undefined : dayNames[dayIndex];
  return name || `${(dayIndex ?? 0) + 1}`;
};
