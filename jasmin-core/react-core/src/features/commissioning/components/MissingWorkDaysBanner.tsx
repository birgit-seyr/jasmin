import { Alert } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useCommissioningSharesDeliveryDaysList } from "@shared/api/generated/commissioning/commissioning";
import { useRoles } from "@shared/auth";
import { useDateFormat, useWashingCleaningVisibility } from "@hooks/index";
import { todayApiDate } from "@shared/utils/apiDate";
import { WEEKDAY_KEYS } from "@shared/utils/weekdayNames";
import { missingWorkDays, shownWorkDayFields } from "../utils/workDays";

/**
 * Red banner over the commissioning pages while a delivery day running today
 * or later lacks a work day: its shares then drop out of the harvest list and
 * the theoretical stock, nothing is planned to be washed or cleaned, and
 * packing falls back to the delivery day. Delivery days a host syncs in arrive
 * without work days. A farm that hides washing or cleaning isn't asked for
 * those days.
 */
export default function MissingWorkDaysBanner() {
  const { t } = useTranslation();
  const { isAdmin } = useRoles();
  const { formatDate } = useDateFormat();
  const { showsWashing, showsCleaning } = useWashingCleaningVisibility();
  const today = todayApiDate();
  const { data } = useCommissioningSharesDeliveryDaysList({
    active_at_date_or_future: today,
  });

  const incompleteDays = useMemo(() => {
    const shownFields = shownWorkDayFields(showsWashing, showsCleaning);
    return (data ?? [])
      .map((day) => ({ day, missing: missingWorkDays(day, shownFields) }))
      .filter(({ missing }) => missing.length > 0);
  }, [data, showsWashing, showsCleaning]);

  if (incompleteDays.length === 0) return null;

  return (
    <Alert
      type="error"
      banner
      showIcon
      message={t("commissioning.missing_work_days.title")}
      description={
        <>
          <ul>
            {incompleteDays.map(({ day, missing }) => (
              <li key={day.id}>
                {t(
                  day.valid_from > today
                    ? "commissioning.missing_work_days.day_from"
                    : "commissioning.missing_work_days.day",
                  {
                    day: t(WEEKDAY_KEYS[day.day_number]),
                    date: formatDate(day.valid_from),
                    missing: missing.map((label) => t(label)).join(", "),
                  },
                )}
              </li>
            ))}
          </ul>
          {t("commissioning.missing_work_days.consequence")}{" "}
          {isAdmin ? (
            <Link to="/configuration/time-management">
              {t("commissioning.missing_work_days.link")}
            </Link>
          ) : (
            t("commissioning.missing_work_days.ask_admin")
          )}
        </>
      }
    />
  );
}
