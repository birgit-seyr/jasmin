import type { SelectOption } from "./types";

/**
 * Clearability for EditableTable selects follows the column's `required` flag —
 * it is the single source of truth. Any select that is not `required: true`
 * gets a leading blank option so the value can be cleared back to empty (the
 * foreignKey save pipeline maps `""` → null, the same shape the old per-column
 * `prependEmpty` used).
 *
 * Idempotent: if the options already carry a clear entry (empty-string, null,
 * or undefined value — e.g. a `useCrates`/`usePlots` null placeholder) they are
 * returned unchanged, so no duplicate blank row appears.
 */
export const withClearOption = (
  options: SelectOption[],
  required: boolean | undefined,
): SelectOption[] => {
  if (required === true) return options;
  const alreadyHasClear = options.some(
    (option) =>
      option.value === "" ||
      option.value === null ||
      option.value === undefined,
  );
  return alreadyHasClear ? options : [{ label: "", value: "" }, ...options];
};
