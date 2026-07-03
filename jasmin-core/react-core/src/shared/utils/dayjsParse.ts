import dayjs from "dayjs";

/**
 * Parse a raw cell / field value into a dayjs for AntD's Date/Time pickers,
 * returning ``null`` for anything that doesn't parse cleanly.
 *
 * A *truthy but invalid* dayjs (e.g. a legacy/partial date, or a value that
 * doesn't match the tenant's ``date_format``) is what pushes rc-picker's
 * internal panel-date math onto a null value and crashes it with "can't
 * access property 'date'". Coercing invalid input to ``null`` makes the
 * picker fall back to today cleanly instead of crashing the page.
 *
 * ``formats`` is passed through to dayjs' customParseFormat; that plugin is
 * registered at boot in ``dayjsSetup.ts``.
 */
export function toValidDayjs(
  value: unknown,
  formats: string[],
): dayjs.Dayjs | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = dayjs(value as string, formats);
  return parsed.isValid() ? parsed : null;
}
