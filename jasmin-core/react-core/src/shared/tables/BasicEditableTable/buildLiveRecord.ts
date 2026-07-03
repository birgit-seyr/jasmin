import type { EditableColumnConfig } from "./types";

/**
 * Merge the in-edit form values into the original record to produce the "live"
 * record that should be passed to per-column callbacks (e.g. `disabled`,
 * `options`).
 *
 * Foreign-key columns hold their selected id under `dataIndex` in the form
 * (because `useEditableTable.edit` rewrites it that way), but consumers
 * typically want to read it back via the underlying `valueField` (e.g.
 * `share_article` instead of `share_article_name`). This helper performs that
 * reverse-mapping.
 */
export function buildLiveRecord<T extends Record<string, unknown>>(
  record: T | null | undefined,
  formValues: Record<string, unknown> | undefined,
  columns: EditableColumnConfig<T>[],
): Record<string, unknown> {
  const merged: Record<string, unknown> = {
    ...(record ?? {}),
    ...(formValues ?? {}),
  };

  if (!formValues) return merged;

  const walk = (cols: EditableColumnConfig<T>[]) => {
    cols.forEach((col) => {
      if (col.foreignKey && col.dataIndex in formValues) {
        merged[col.foreignKey.valueField] = formValues[col.dataIndex];
      }
      if (col.children) {
        walk(col.children);
      }
    });
  };
  walk(columns);

  return merged;
}
