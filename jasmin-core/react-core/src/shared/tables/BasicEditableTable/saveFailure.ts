import { getErrorMessage } from "@shared/utils/apiError";
import { nodeText } from "./nodeText";
import type { EditableColumnConfig, TableRecord } from "./types";

/** The keys under which a refusal speaks about the row as a whole rather than
 *  one of its fields: DRF's `non_field_errors`, the canonical shape's `_errors`
 *  and Django's model-wide `__all__`. They name no column, so they neither
 *  border a cell nor lead the banner. */
const NON_FIELD_KEYS = ["non_field_errors", "_errors", "__all__"];

/** The field → message pairs in `source`, but for the `skip` keys: list values
 *  always, a plain string value only when `listsOnly` is off. */
function fieldMessages(
  source: Record<string, unknown>,
  skip: ReadonlySet<string>,
  listsOnly: boolean,
): Record<string, string> {
  const messages: Record<string, string> = {};
  for (const [field, value] of Object.entries(source)) {
    if (skip.has(field)) continue;
    if (Array.isArray(value) && typeof value[0] === "string") {
      messages[field] = value[0];
    } else if (!listsOnly && typeof value === "string") {
      messages[field] = value;
    }
  }
  return messages;
}

/**
 * What a failed save shows: the per-field messages behind the red borders, and
 * the banner, led by the titles of the fields at fault. The backend speaks two
 * shapes: DRF's top-level `{field: ["msg"]}`, and the canonical
 * `{code, message, details}`, whose `details` hold per-field lists beside
 * scalar context for the coded message (an over-capacity error's
 * `station_day_id`, `year`, `week`) — only the lists name fields.
 */
export function describeSaveFailure<T extends TableRecord>(
  error: unknown,
  columns: EditableColumnConfig<T>[],
  fallbackMessage: string,
): { fieldErrors: Record<string, string>; message: string } {
  const body = (error as { response?: { data?: unknown } } | null)?.response
    ?.data;
  const fieldErrors: Record<string, string> = {};
  if (body && typeof body === "object") {
    const { details } = body as { details?: unknown };
    Object.assign(
      fieldErrors,
      fieldMessages(
        body as Record<string, unknown>,
        new Set([
          "code",
          "message",
          "details",
          "request_id",
          "field",
          ...NON_FIELD_KEYS,
        ]),
        false,
      ),
      details && typeof details === "object"
        ? fieldMessages(
            details as Record<string, unknown>,
            new Set(NON_FIELD_KEYS),
            true,
          )
        : {},
    );
  }
  const message = getErrorMessage(error, fallbackMessage);
  const titles = Object.keys(fieldErrors).map(
    (field) =>
      nodeText(columns.find((column) => column.dataIndex === field)?.title) ||
      field,
  );
  return {
    fieldErrors,
    message: titles.length > 0 ? `${titles.join(", ")}: ${message}` : message,
  };
}
