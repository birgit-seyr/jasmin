import { parseDateLoose } from "@shared/utils/endOfTerm";
import type { AboRecord } from "./types";

export interface ValidationResult {
  isValid: boolean;
  message?: string;
  /** When invalid because of date range, the formatted bounds so the
   *  caller can interpolate them into the user-facing message. */
  validFrom?: string;
  validUntil?: string;
}

/**
 * ``cancelled_effective_at`` must fall inside
 * ``[valid_from, valid_until]`` (inclusive) when present. Used by the
 * Abos table's ``customSave`` to reject malformed input before the
 * round-trip — the backend enforces the same constraint server-side.
 *
 * Pure function for testability: no ``useTranslation`` /
 * ``notify.*`` here. Caller resolves i18n based on the returned
 * ``messageKey`` or falls back to the raw ``message``.
 */
export function validateCancelledDate(
  record: AboRecord,
  dateFormat: string,
): ValidationResult & { messageKey?: string } {
  if (!record.cancelled_effective_at) {
    return { isValid: true };
  }

  if (!record.valid_from || !record.valid_until) {
    return {
      isValid: false,
      messageKey: "validation.valid_dates_required_for_cancellation",
    };
  }

  const cancelled = parseDateLoose(record.cancelled_effective_at, dateFormat);
  const validFrom = parseDateLoose(record.valid_from, dateFormat);
  const validUntil = parseDateLoose(record.valid_until, dateFormat);

  if (!cancelled || !validFrom || !validUntil) {
    return {
      isValid: false,
      messageKey: "validation.invalid_date_format",
    };
  }

  if (
    cancelled.isSame(validFrom, "day") ||
    cancelled.isSame(validUntil, "day") ||
    (cancelled.isAfter(validFrom, "day") && cancelled.isBefore(validUntil, "day"))
  ) {
    return { isValid: true };
  }

  return {
    isValid: false,
    messageKey: "validation.cancelled_date_must_be_between_valid_dates",
    validFrom: validFrom.format(dateFormat),
    validUntil: validUntil.format(dateFormat),
  };
}
