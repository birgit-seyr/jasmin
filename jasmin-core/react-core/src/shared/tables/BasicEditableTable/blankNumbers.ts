import type { EditableColumnConfig, InputType } from "./types";

const NUMBER_INPUT_TYPES: ReadonlySet<InputType> = new Set<InputType>([
  "number",
  "integer",
  "positive_integer",
  "negative_integer",
  "decimal1",
  "decimal2",
  "decimal3",
  "positive_decimal2",
  "negative_decimal2",
  "positive_decimal3",
  "negative_decimal3",
  "percentage",
  "kw",
]);

/**
 * The row with every cleared optional number cell set to null. A cleared
 * number input holds an empty string, which the backend's number fields
 * refuse ("A valid integer is required."), while null clears the field. A
 * required number column keeps its value as typed, so a blank one is still
 * refused rather than silently cleared. The table applies it after a page's
 * `customSave`, which still gets a cleared cell as typed.
 */
export function blankOptionalNumbersToNull<T extends Record<string, unknown>>(
  row: Record<string, unknown>,
  columns: EditableColumnConfig<T>[],
): Record<string, unknown> {
  const cleared = columns.filter(
    (column) =>
      column.inputType !== undefined &&
      NUMBER_INPUT_TYPES.has(column.inputType) &&
      column.required !== true &&
      typeof row[column.dataIndex] === "string" &&
      (row[column.dataIndex] as string).trim() === "",
  );
  if (cleared.length === 0) return row;
  const result = { ...row };
  cleared.forEach((column) => {
    result[column.dataIndex] = null;
  });
  return result;
}
