import { Alert, Select } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useRoles } from "@shared/auth";
import { ToolTipIcon } from "@shared/ui";
import {
  missingOrderDays,
  type OrderDayConfig,
} from "@features/commissioning/utils/orderDays";
import type {
  OddDefaults,
  OrderDays,
} from "@features/commissioning/hooks/useOrdersData";

const DAY_OPTIONS = [
  { value: 0, label: "MO" },
  { value: 1, label: "DI" },
  { value: 2, label: "MI" },
  { value: 3, label: "DO" },
  { value: 4, label: "FR" },
  { value: 5, label: "SA" },
  { value: 6, label: "SO" },
];

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
  const missing = missingOrderDays(days, orderDays, orderId);
  return (
    <>
      <div
        style={{
          marginTop: "1.5em",
          marginBottom: "1.5em",
          display: "flex",
          gap: "1em",
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        {tooltip && <ToolTipIcon title={tooltip} />}
        {days.map(({ label, field, defaultField }) => {
          const differs =
            orderId != null &&
            oddDefaults[defaultField] != null &&
            orderDays[field] !== oddDefaults[defaultField];

          return (
            <div
              key={field}
              className="flex-center-y"
              style={{ gap: "0.25em" }}
            >
              <span
                style={{
                  color: differs ? "red" : undefined,
                  fontWeight: differs ? "bold" : undefined,
                }}
              >
                {label}:
              </span>
              <Select
                style={{ width: 80 }}
                className={differs ? "day-select-differs" : "day-select-violet"}
                value={orderDays[field]}
                onChange={(val) => onDayChange(field, val)}
                options={DAY_OPTIONS}
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
