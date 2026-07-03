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
}

export const useTimeBoundColumns = (options: TimeBoundColumnOptions = {}) => {
  const {
    validFromRequired = true,
    validUntilRequired = false,
    width = "10em",
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

  const disabledDateNotSunday = useMemo(
    () => (current: unknown) => !!current && (current as Dayjs).day() !== 0,
    [],
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
      disabledDate: disabledDateNotSunday,
      render: (value: unknown) => (value ? dayjs(value as string).format(dateFormat) : ""),
    }),
    [t, dateFormat, validUntilRequired, width, disabledDateNotSunday],
  );

  return { validFromColumn, validUntilColumn };
};
