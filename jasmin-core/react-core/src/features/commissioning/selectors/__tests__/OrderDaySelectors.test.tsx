/**
 * OrderDaySelectors: the four work-day selects of an order, each named by its
 * label, and the hint a new order shows while one of its days is missing —
 * pointing an admin to the order-day defaults and telling the office who can
 * set them.
 */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  OddDefaults,
  OrderDays,
} from "@features/commissioning/hooks/useOrdersData";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: unknown) =>
      options && typeof options === "object" && "days" in options
        ? `${key}: ${String((options as { days: unknown }).days)}`
        : typeof options === "string"
          ? options
          : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const roles = vi.hoisted(() => ({ isAdmin: false }));
vi.mock("@shared/auth", () => ({
  useRoles: () => ({ isOffice: true, isAdmin: roles.isAdmin }),
}));

vi.mock("@shared/ui", () => ({ ToolTipIcon: () => null }));

import { OrderDaySelectors } from "../OrderDaySelectors";

const DAYS = [
  {
    label: "Harvest day",
    field: "harvesting_day" as const,
    defaultField: "default_harvesting_day" as const,
  },
  {
    label: "Washing day",
    field: "washing_day" as const,
    defaultField: "default_washing_day" as const,
  },
  {
    label: "Cleaning day",
    field: "cleaning_day" as const,
    defaultField: "default_cleaning_day" as const,
  },
  {
    label: "Commissioning day",
    field: "packing_day" as const,
    defaultField: "default_packing_day" as const,
  },
];

const NO_DAYS: OrderDays = {
  harvesting_day: null,
  packing_day: null,
  washing_day: null,
  cleaning_day: null,
};
const NO_DEFAULTS: OddDefaults = {
  default_harvesting_day: null,
  default_packing_day: null,
  default_washing_day: null,
  default_cleaning_day: null,
};
const ALL_DAYS: OrderDays = {
  harvesting_day: 1,
  packing_day: 3,
  washing_day: 2,
  cleaning_day: 2,
};

function renderSelectors(
  props: Partial<React.ComponentProps<typeof OrderDaySelectors>> = {},
) {
  return render(
    <MemoryRouter>
      <OrderDaySelectors
        days={DAYS}
        orderDays={NO_DAYS}
        oddDefaults={NO_DEFAULTS}
        orderId={null}
        onDayChange={() => {}}
        {...props}
      />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  roles.isAdmin = false;
});

describe("OrderDaySelectors", () => {
  it("names each day select by its label", () => {
    renderSelectors({ orderDays: ALL_DAYS });

    for (const { label } of DAYS) {
      expect(screen.getByRole("combobox", { name: label })).toBeInTheDocument();
    }
  });

  it("tells the office which days a new order lacks and who sets their defaults", () => {
    renderSelectors({
      orderDays: { ...ALL_DAYS, harvesting_day: null, packing_day: null },
    });

    expect(
      screen.getByText(
        "commissioning.order_days_missing: Harvest day, Commissioning day",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("commissioning.order_days_defaults_missing_office"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("links an admin to where the order-day defaults are set", () => {
    roles.isAdmin = true;
    renderSelectors();

    expect(
      screen.getByRole("link", {
        name: "commissioning.order_days_defaults_link",
      }),
    ).toHaveAttribute("href", "/configuration/time-management");
  });

  it("only names the missing days when their defaults exist", () => {
    renderSelectors({
      orderDays: { ...ALL_DAYS, washing_day: null },
      oddDefaults: { ...NO_DEFAULTS, default_washing_day: 2 },
    });

    expect(
      screen.getByText("commissioning.order_days_missing: Washing day"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("commissioning.order_days_defaults_missing_office"),
    ).not.toBeInTheDocument();
  });

  it("shows no hint once every day is picked, for an existing order or while loading", () => {
    const { unmount } = renderSelectors({ orderDays: ALL_DAYS });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    unmount();

    const existing = renderSelectors({ orderId: "order-1" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    existing.unmount();

    renderSelectors({ loading: true });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
