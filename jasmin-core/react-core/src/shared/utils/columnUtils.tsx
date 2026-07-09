import dayjs from "dayjs";
import type { Key, ReactElement } from "react";
import type { TFunction } from "i18next";

type DateInput = string | number | Date | null | undefined;
type DateRangeStatus = "active" | "future" | "inactive";

export const getDateRangeStatus = (
  validFrom: unknown,
  validUntil: unknown,
): DateRangeStatus => {
  const today = dayjs().startOf("day");
  const fromDate = dayjs(validFrom as DateInput).startOf("day");

  // If no valid_until, treat as open-ended (active if started)
  if (!validUntil) {
    if (today.isSameOrAfter(fromDate)) {
      return "active";
    } else {
      return "future";
    }
  }

  const untilDate = dayjs(validUntil as DateInput).startOf("day");

  // Check if subscription is in the future
  if (today.isBefore(fromDate)) {
    return "future";
  }

  // Check if subscription is currently active
  if (today.isSameOrAfter(fromDate) && today.isSameOrBefore(untilDate)) {
    return "active";
  }

  // Otherwise it's inactive (past)
  return "inactive";
};

// Single colour map for the three date-range buckets — the SSOT for both the
// status-dot renderer and `getStatusColor` so the two can never drift.
export const DATE_RANGE_STATUS_COLOR: Record<DateRangeStatus, string> = {
  active: "var(--color-success)", // Green
  future: "var(--color-future-blue)", // Blue
  inactive: "var(--color-border)", // Gray
};

export const createDateRangeStatusSorter = (
  validFromField = "valid_from",
  validUntilField = "valid_until",
) => {
  return (a: Record<string, unknown>, b: Record<string, unknown>): number => {
    const statusA = getDateRangeStatus(
      a[validFromField] as DateInput,
      a[validUntilField] as DateInput,
    );
    const statusB = getDateRangeStatus(
      b[validFromField] as DateInput,
      b[validUntilField] as DateInput,
    );

    // Define sort order: future > active > inactive — descending puts upcoming
    // rows on top, then the currently-active row, then expired ones.
    const statusOrder: Record<DateRangeStatus, number> = {
      future: 3,
      active: 2,
      inactive: 1,
    };

    return statusOrder[statusA] - statusOrder[statusB];
  };
};

interface StatusConfigEntry {
  color: string;
  tooltip: string;
}

interface DateRangeRendererOptions {
  validFromField?: string;
  validUntilField?: string;
  size?: number;
  statusConfig?: Record<DateRangeStatus, StatusConfigEntry>;
}

export const createDateRangeStatusRenderer = (
  t: TFunction,
  options: DateRangeRendererOptions = {},
) => {
  const {
    validFromField = "valid_from",
    validUntilField = "valid_until",
    size = 12,
    statusConfig = {
      active: {
        color: DATE_RANGE_STATUS_COLOR.active,
        tooltip: t("members.currently_active"),
      },
      future: {
        color: DATE_RANGE_STATUS_COLOR.future,
        tooltip: t("members.future_active"),
      },
      inactive: {
        color: DATE_RANGE_STATUS_COLOR.inactive,
        tooltip: t("members.currently_inactive"),
      },
    },
  } = options;

  return (_: unknown, record: Record<string, unknown>): ReactElement => {
    const status = getDateRangeStatus(
      record[validFromField] as DateInput,
      record[validUntilField] as DateInput,
    );
    const config = statusConfig[status];

    return (
      // The status is otherwise colour-only — role="img" + aria-label give the
      // dot an accessible name so screen readers announce active/future/inactive
      // (no visual change).
      <div
        role="img"
        aria-label={config.tooltip}
        style={{
          width: `${size}px`,
          height: `${size}px`,
          backgroundColor: config.color,
          borderRadius: "2px",
          margin: "0 auto",
        }}
        title={config.tooltip}
      />
    );
  };
};

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
