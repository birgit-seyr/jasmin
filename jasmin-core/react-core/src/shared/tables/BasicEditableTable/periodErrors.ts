import dayjs, { type ConfigType } from "dayjs";
import type { Key } from "react";
import { messageForErrorCode } from "@shared/utils/apiError";
import { formatApiDate } from "@shared/utils/apiDate";
import { otherRows, sameCellValue } from "./duplicateErrors";
import type { EditableColumnConfig, TableRecord } from "./types";

type Row = Record<string, unknown>;

/** A date value as `YYYY-MM-DD`; null when there is none. */
function isoDay(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const day = dayjs(value as ConfigType);
  return day.isValid() ? formatApiDate(day) : null;
}

const inGroup = (group: readonly string[], a: Row, b: Row): boolean =>
  group.every((field) => sameCellValue(a[field], b[field]));

/**
 * Whether two rows' validity periods share a day. Both days count, and a row
 * without `valid_until` runs on with no end.
 */
export function periodsOverlap(a: Row, b: Row): boolean {
  const aFrom = isoDay(a.valid_from);
  const bFrom = isoDay(b.valid_from);
  if (aFrom === null || bFrom === null) return false;
  const aUntil = isoDay(a.valid_until);
  const bUntil = isoDay(b.valid_until);
  return (
    (bUntil === null || aFrom <= bUntil) && (aUntil === null || bFrom <= aUntil)
  );
}

/**
 * The rows valid on a day `edited` covers once the backend has saved it, out
 * of `rows` (which leave `edited` itself out). Saving a NEW row closes the open
 * row of its overlap group — the rows with its values in `group`, the
 * backend's `overlap_unique_fields` — the day before it starts, when that row
 * starts earlier; that one no longer counts.
 */
export function concurrentRows<T extends Row>(
  rows: T[],
  edited: Row,
  { group, isNew }: { group: readonly string[]; isNew: boolean },
): T[] {
  const editedFrom = isoDay(edited.valid_from);
  return rows.filter((other) => {
    const otherFrom = isoDay(other.valid_from);
    const closedBySave =
      isNew &&
      inGroup(group, other, edited) &&
      isoDay(other.valid_until) === null &&
      otherFrom !== null &&
      editedFrom !== null &&
      otherFrom < editedFrom;
    return !closedBySave && periodsOverlap(other, edited);
  });
}

function overlapMessage(existing: Row): string {
  const existingUntil = isoDay(existing.valid_until);
  return (
    messageForErrorCode("time_bound.overlap", {
      existing_valid_from: isoDay(existing.valid_from),
      existing_valid_until: existingUntil,
      context: existingUntil === null ? "open" : undefined,
    }) ?? "The period overlaps an existing record."
  );
}

/**
 * The field error for a row whose validity the backend would refuse within
 * the overlap group a `valid_from` column's `overlapGroup` names, in the
 * backend's own words: a new row may not start before the group's open row
 * (succeeding it would end that row before its start), and no two rows of a
 * group may share a day. Marks the start when the row begins inside the other
 * row's period, the end when it reaches into it. Empty when the period is
 * fine, has no start yet, or no column names a group.
 */
export function periodErrors<T extends TableRecord>({
  columns,
  rows,
  extraRows,
  key,
  row,
}: {
  columns: EditableColumnConfig<T>[];
  rows: T[];
  extraRows?: T[];
  key: Key;
  row: Row;
}): Record<string, string> {
  const group = columns.find((column) => column.overlapGroup)?.overlapGroup;
  const editedFrom = isoDay(row.valid_from);
  if (!group || editedFrom === null) return {};
  const isNew = key === -1;
  const siblings = otherRows({ rows, extraRows, key }).filter((other) =>
    inGroup(group, other, row),
  );

  const laterOpen = siblings.find((other) => {
    const otherFrom = isoDay(other.valid_from);
    return (
      isNew &&
      isoDay(other.valid_until) === null &&
      otherFrom !== null &&
      otherFrom > editedFrom
    );
  });
  if (laterOpen) {
    return {
      valid_from:
        messageForErrorCode("time_bound.succession_start_before_predecessor", {
          new_valid_from: editedFrom,
          existing_valid_from: isoDay(laterOpen.valid_from),
        }) ?? "The period starts before the open record it would succeed.",
    };
  }

  const [clash] = concurrentRows(siblings, row, { group, isNew });
  if (!clash) return {};
  const startsInside = editedFrom >= (isoDay(clash.valid_from) ?? "");
  return { [startsInside ? "valid_from" : "valid_until"]: overlapMessage(clash) };
}
