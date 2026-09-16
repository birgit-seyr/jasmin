import type { Key } from "react";
import { DATE_RANGE_STATUS_COLOR, getDateRangeStatus } from "./dateRangeStatus";

interface FieldDisabledRecord {
  key?: Key | null;
  can_be_deleted?: boolean | null;
}

export const isFieldDisabled = (
  record: FieldDisabledRecord,
  allowNewRecords = true,
): boolean => {
  // Allow editing for new records (key === -1) if allowNewRecords is true
  if (record.key === -1) {
    return !allowNewRecords;
  }

  // If can_be_deleted is undefined or null, allow editing
  if (record.can_be_deleted === undefined || record.can_be_deleted === null) {
    return false;
  }

  // Disable if record cannot be deleted
  return !record.can_be_deleted;
};

/**
 * "Editable only on a new row" predicate. New rows carry the sentinel key
 * `-1`; every persisted row has a real key, so its cell stays locked. This is
 * a DIFFERENT rule from {@link isFieldDisabled} (which keys off
 * `can_be_deleted`) — it's purely new-vs-existing, so a column using it locks
 * the cell on every saved row.
 */
export const editableOnlyOnCreate = (
  record: Record<string, unknown>,
): boolean => record.key !== -1;

export const getStatusColor = (
  validFrom: unknown,
  validUntil: unknown,
): string => DATE_RANGE_STATUS_COLOR[getDateRangeStatus(validFrom, validUntil)];
