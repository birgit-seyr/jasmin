import dayjs, { type Dayjs } from "dayjs";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { EditableColumnConfig, TableRecord } from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { isFieldDisabled } from "@shared/utils";
import { useDateFormat } from "../configuration/useDateFormat";

/**
 * Returns reusable valid_from (Monday-only) and valid_until (Sunday-only)
 * column definitions for any EditableTable backed by a TimeBoundMixin model.
 */
interface TimeBoundColumnOptions {
  validFromRequired?: boolean;
  validUntilRequired?: boolean;
  width?: string;
  /**
   * Restrict ``valid_from`` to the first Monday on or after today — no past
   * dates. Use on forward-looking operational configs (delivery days, station
   * days, delivery-exception periods) where a past start is never valid (the
   * backend already rejects it). Already-saved past rows keep rendering; the
   * floor only blocks NEW selections, and ``isFieldDisabled`` already locks
   * ``valid_from`` on saved in-use rows. Default ``false`` — catalogue / price /
   * back-dated surfaces keep the past open.
   */
  validFromFutureOnly?: boolean;
  /**
   * Per-row lower bound for ``valid_until``: dates before ``minDate`` are
   * disabled, and ``blockAll`` disables EVERY date (a still-active child — e.g.
   * an open-ended subscription/variation — makes any end date invalid). Stops
   * the office picking an end date the backend would reject for stranding
   * children. (The cross-field ``valid_until > valid_from`` rule is always
   * enforced separately, regardless of this option.)
   */
  validUntilFloor?: (record: TableRecord) => {
    minDate?: Dayjs | null;
    blockAll?: boolean;
  };
}

export const useTimeBoundColumns = (options: TimeBoundColumnOptions = {}) => {
  const {
    validFromRequired = true,
    validUntilRequired = false,
    width = "10em",
    validFromFutureOnly = false,
    validUntilFloor,
  } = options;

  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();

  // The first Monday on or after today (equal to today when today is a Monday,
  // otherwise next Monday) — the earliest a future-only ``valid_from`` may be.
  // Core ``day()`` (0=Sun … 6=Sat), no isoWeek plugin (see below).
  const earliestValidFrom = useMemo(() => {
    const today = dayjs().startOf("day");
    const monday = today.day(1); // Monday of the current (Sun–Sat) week
    return monday.isBefore(today, "day") ? monday.add(7, "day") : monday;
  }, []);

  // valid_from: Mondays only, and — when ``validFromFutureOnly`` — not before
  // the first upcoming Monday. Uses core ``day()`` rather than the ``isoWeek``
  // plugin's ``isoWeekday()``: ``day()`` needs no ``dayjs.extend`` and is
  // immune to chunk load-order. Relying on the plugin here crashed the picker
  // in production whenever this column mounted before any module that had
  // ``dayjs.extend(isoWeek)``'d as a side effect (``isoWeekday`` undefined).
  const disabledDateValidFrom = useMemo(
    () => (current: unknown) => {
      const day = current as Dayjs | undefined;
      if (!day) return false;
      if (day.day() !== 1) return true;
      if (validFromFutureOnly && day.isBefore(earliestValidFrom, "day")) {
        return true;
      }
      return false;
    },
    [validFromFutureOnly, earliestValidFrom],
  );

  // valid_until: Sundays only; strictly AFTER the (live) valid_from — a range
  // end can never precede its start; and not before any supplied per-row floor
  // (a still-active child forces the row open-ended → blockAll).
  const disabledDateValidUntil = useMemo(
    () => (current: unknown, record?: TableRecord) => {
      const day = current as Dayjs | undefined;
      if (!day) return false;
      if (day.day() !== 0) return true;
      // Cross-field: ``record`` is the live row (form values merged), so this
      // tracks the valid_from the office just picked. valid_until must land
      // after it — the backend enforces the same rule.
      const validFromRaw = record?.valid_from;
      if (validFromRaw) {
        const validFrom = dayjs(validFromRaw as string);
        if (validFrom.isValid() && !day.isAfter(validFrom, "day")) return true;
      }
      if (validUntilFloor && record) {
        const { minDate, blockAll } = validUntilFloor(record);
        if (blockAll) return true;
        if (minDate && day.isBefore(minDate, "day")) return true;
      }
      return false;
    },
    [validUntilFloor],
  );

  const validFromColumn = useMemo<EditableColumnConfig<TableRecord>>(
    () => ({
      title: (
        <>
          {t("configuration.valid_from")}
          <ToolTipIcon title={t("configuration.valid_from_must_be_monday")} />
        </>
      ),
      dataIndex: "valid_from",
      key: "valid_from",
      inputType: "datepicker",
      required: validFromRequired,
      width,
      align: "center",
      disabledDate: disabledDateValidFrom,
      disabled: isFieldDisabled,
      render: (value: unknown) => (value ? dayjs(value as string).format(dateFormat) : (value as string)),
    }),
    [t, dateFormat, validFromRequired, width, disabledDateValidFrom],
  );

  const validUntilColumn = useMemo<EditableColumnConfig<TableRecord>>(
    () => ({
      title: (
        <>
          {t("configuration.valid_until")}
          <ToolTipIcon title={t("configuration.valid_until_must_be_sunday")} />
        </>
      ),
      dataIndex: "valid_until",
      key: "valid_until",
      inputType: "datepicker",
      required: validUntilRequired,
      width,
      align: "center",
      disabledDate: disabledDateValidUntil,
      render: (value: unknown) => (value ? dayjs(value as string).format(dateFormat) : ""),
    }),
    [t, dateFormat, validUntilRequired, width, disabledDateValidUntil],
  );

  return { validFromColumn, validUntilColumn };
};
