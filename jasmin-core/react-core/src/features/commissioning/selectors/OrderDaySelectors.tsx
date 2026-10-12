import { useMemo } from "react";
import { Alert, Select } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useRoles } from "@shared/auth";
import { ToolTipIcon } from "@shared/ui";
import { getWeekdayChoices } from "@shared/utils/weekdayChoices";
import {
  missingOrderDays,
  type OrderDayConfig,
} from "@features/commissioning/utils/orderDays";
import type {
  OddDefaults,
  OrderDays,
} from "@features/commissioning/hooks/useOrdersData";

interface OrderDaySelectorsProps {
  days: OrderDayConfig[];
  orderDays: OrderDays;
  oddDefaults: OddDefaults;
  orderId: string | number | null;
  onDayChange: (field: keyof OrderDays, value: number | null) => void;
  /** One tooltip explaining the whole harvest / washing / commissioning-day group. */
  tooltip?: string;
  /** While the order is read, its days aren't known yet: no hint shows. */
  loading?: boolean;
}

function MissingOrderDaysHint({
  missing,
  oddDefaults,
}: {
  missing: OrderDayConfig[];
  oddDefaults: OddDefaults;
}) {
  const { t } = useTranslation();
  const { isAdmin } = useRoles();
  const defaultsMissing = missing.some(
    ({ defaultField }) => oddDefaults[defaultField] == null,
  );
  let description = null;
  if (defaultsMissing) {
    description = isAdmin ? (
      <>
        {t("commissioning.order_days_defaults_missing_admin")}{" "}
        <Link to="/configuration/time-management">
          {t("commissioning.order_days_defaults_link")}
        </Link>
      </>
    ) : (
      t("commissioning.order_days_defaults_missing_office")
    );
  }
  return (
    <Alert
      type="warning"
      showIcon
      className="mb-1em"
      message={t("commissioning.order_days_missing", {
        days: missing.map(({ label }) => label).join(", "),
      })}
      description={description}
    />
  );
}

export function OrderDaySelectors({
  days,
  orderDays,
  oddDefaults,
  orderId,
  onDayChange,
  tooltip,
  loading = false,
}: OrderDaySelectorsProps) {
  const { t } = useTranslation();
  // Work days may fall on a Sunday although deliveries don't, so the order
  // days offer it on top of the delivery weekdays.
  const dayOptions = useMemo(
    () => [
      ...getWeekdayChoices(t),
      { value: 6, label: t("configuration.acronym_sunday") },
    ],
    [t],
  );
  const missing = missingOrderDays(days, orderDays, orderId);
  return (
    <>
      <div className="order-day-selectors">
        {tooltip && <ToolTipIcon title={tooltip} />}
        {days.map(({ label, field, defaultField }) => {
          const differs =
            orderId != null &&
            oddDefaults[defaultField] != null &&
            orderDays[field] !== oddDefaults[defaultField];

          return (
            <div key={field} className="flex-center-y order-day-selector">
              <span className={differs ? "order-day-label-differs" : undefined}>
                {label}:
              </span>
              <Select
                className={differs ? "day-select-differs" : "day-select-violet"}
                value={orderDays[field]}
                onChange={(val) => onDayChange(field, val)}
                options={dayOptions}
                disabled={orderId != null}
                allowClear
                size="small"
                aria-label={label}
              />
            </div>
          );
        })}
      </div>
      {!loading && missing.length > 0 && (
        <MissingOrderDaysHint missing={missing} oddDefaults={oddDefaults} />
      )}
    </>
  );
}
