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
        color: "var(--color-success)", // Green
        tooltip: t("members.currently_active"),
      },
      future: {
        color: "var(--color-future-blue)", // Blue
        tooltip: t("members.future_active"),
      },
      inactive: {
        color: "var(--color-border)", // Gray
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
      <div
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

export const getStatusColor = (
  validFrom: unknown,
  validUntil: unknown,
): string => {
  const now = dayjs();
  const from = validFrom ? dayjs(validFrom as DateInput) : null;
  const until = validUntil ? dayjs(validUntil as DateInput) : null;

  // Future (blue) - valid_from is in the future
  if (from && from.isAfter(now, "day")) {
    return "var(--color-future-blue)"; // blue
  }

  // Past (grey) - valid_until is in the past
  if (until && until.isBefore(now, "day")) {
    return "var(--color-border)"; // grey
  }

  // Active (green) - currently valid or no end date
  return "var(--color-success)"; // green
};
