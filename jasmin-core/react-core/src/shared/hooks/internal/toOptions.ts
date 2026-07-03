/**
 * Tiny helper that collapses the repeated pattern used by ~15 list hooks:
 *
 *   const items = (data ?? []).map((item) => ({
 *     value: item.id!,
 *     label: makeLabel(item),
 *     ...item,
 *   }));
 *
 * Returns an array of items augmented with `value` and `label` so they can
 * be fed directly into antd selects.
 */
export type Option<T> = T & { value: string; label: string };
export type NullableOption<T> = Option<T> | { value: null; label: string };

export function toOptions<T extends { id?: string | null }>(
  data: T[] | null | undefined,
  toLabel: (item: T) => string,
): Option<T>[] {
  // Rows without an id can't back a select option — skip them instead of
  // pretending their id is a string.
  return (data ?? []).flatMap((item) =>
    item.id == null
      ? []
      : [{ ...item, value: item.id, label: toLabel(item) }],
  );
}

/**
 * Same as toOptions but prepends a `{ value: null, label }` placeholder used
 * by selects that allow "no selection".
 */
export function toOptionsWithNull<T extends { id?: string | null }>(
  data: T[] | null | undefined,
  toLabel: (item: T) => string,
  nullLabel = "-",
): NullableOption<T>[] {
  return [
    { value: null, label: nullLabel },
    ...toOptions(data, toLabel),
  ];
}
