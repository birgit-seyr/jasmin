import { Select } from "antd";
import { ToolTipIcon } from "@shared/ui";
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

interface DayConfig {
  label: string;
  field: keyof OrderDays;
  defaultField: keyof OddDefaults;
}

interface OrderDaySelectorsProps {
  days: DayConfig[];
  orderDays: OrderDays;
  oddDefaults: OddDefaults;
  orderId: string | number | null;
  onDayChange: (field: keyof OrderDays, value: number | null) => void;
  /** One tooltip explaining the whole harvest / washing / commissioning-day group. */
  tooltip?: string;
}

export function OrderDaySelectors({
  days,
  orderDays,
  oddDefaults,
  orderId,
  onDayChange,
  tooltip,
}: OrderDaySelectorsProps) {
  return (
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
          <div key={field} className="flex-center-y" style={{ gap: "0.25em" }}>
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
            />
          </div>
        );
      })}
    </div>
  );
}
