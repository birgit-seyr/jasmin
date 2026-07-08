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
   * Per-row lower bound for ``valid_until``: dates before ``minDate`` are
   * disabled, and ``blockAll`` disables EVERY date (a still-active child — e.g.
   * an open-ended subscription/variation — makes any end date invalid). Stops
   * the office picking an end date the backend would reject for stranding
   * children.
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
    validUntilFloor,
  } = options;

  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();

  // Use core ``day()`` (0=Sun … 6=Sat) rather than the ``isoWeek`` plugin's
  // ``isoWeekday()``: ``day()`` needs no ``dayjs.extend`` and is therefore
  // immune to chunk load-order. Relying on the plugin here crashed the picker
  // in production whenever this column mounted before any module that had
  // ``dayjs.extend(isoWeek)``'d as a side effect (``isoWeekday`` undefined).
  const disabledDateNotMonday = useMemo(
    () => (current: unknown) => !!current && (current as Dayjs).day() !== 1,
    [],
  );

  // valid_until: Sundays only, AND (when a floor resolver is supplied) not
  // before the row's floor — every date is blocked while a still-active child
  // forces the row open-ended.
  const disabledDateValidUntil = useMemo(
    () => (current: unknown, record?: TableRecord) => {
      const day = current as Dayjs | undefined;
      if (!day) return false;
      if (day.day() !== 0) return true;
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
      disabledDate: disabledDateNotMonday,
      disabled: isFieldDisabled,
      render: (value: unknown) => (value ? dayjs(value as string).format(dateFormat) : (value as string)),
    }),
    [t, dateFormat, validFromRequired, width, disabledDateNotMonday],
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
