// PaymentsCard reads the ChargeSchedule ledger (the source of truth) and
// renders a payment timeline. These tests lock the ledger logic: array vs
// {results} envelope handling, the no-member empty state, and that a WAIVED
// (forgiven) charge is shown but excluded from the date total.

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dayjs from "dayjs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const chargesHook = vi.fn();
vi.mock(
  "@shared/api/generated/payments-—-charge-schedule/payments-—-charge-schedule",
  () => ({
    usePaymentsChargeSchedulesList: (...args: unknown[]) => chargesHook(...args),
  }),
);

vi.mock("@hooks/index", () => ({
  useCurrency: () => ({
    currencySymbol: "€",
    formatCurrency: (n: number) => `${n.toFixed(2)} €`,
  }),
  useNumberFormat: () => ({ format: (n: number) => n.toFixed(2) }),
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    mobileDateFormat: "DD.MM.",
    formatDate: (v: unknown) =>
      v == null || v === ""
        ? null
        : dayjs(v as dayjs.ConfigType).format("DD.MM.YYYY"),
  }),
}));

vi.mock("@features/members/modals/SepaSetupModal", () => ({ default: () => null }));

import PaymentsCard from "../PaymentsCard";

function renderCard(props: { memberId?: string }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <PaymentsCard {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  chargesHook.mockReset();
  chargesHook.mockReturnValue({ data: undefined });
});

describe("PaymentsCard", () => {
  it("shows the empty state and disables the query when there is no member", () => {
    renderCard({});
    expect(screen.getByText("members.no_payments")).toBeInTheDocument();
    const [, options] = chargesHook.mock.calls[0];
    expect((options as { query: { enabled: boolean } }).query.enabled).toBe(
      false,
    );
  });

  it("excludes a WAIVED charge from the date total but still shows it", () => {
    chargesHook.mockReturnValue({
      data: [
        {
          id: "1",
          due_date: "2099-02-01",
          expected_amount: "45.00",
          subscription_label: "HarvestShare M",
          status: "PLANNED",
        },
        {
          id: "2",
          due_date: "2099-02-01",
          expected_amount: "5.00",
          subscription_label: "EggShare",
          status: "PLANNED",
        },
        {
          id: "3",
          due_date: "2099-02-01",
          expected_amount: "100.00",
          subscription_label: "Forgiven",
          status: "WAIVED",
        },
      ],
    });
    renderCard({ memberId: "m1" });

    // The WAIVED line is rendered (visible) with its status tag …
    expect(screen.getByText("abos.charge_status.WAIVED")).toBeInTheDocument();
    expect(screen.getByText(/100\.00/)).toBeInTheDocument();
    // … but the date total is 50.00 (45 + 5), NOT 150.00.
    expect(screen.getByText("members.total")).toBeInTheDocument();
    expect(screen.getByText(/50\.00/)).toBeInTheDocument();
    expect(screen.queryByText(/150\.00/)).not.toBeInTheDocument();
  });

  it("sums a monthly batch labelled by month when every sub is monthly", () => {
    chargesHook.mockReturnValue({
      data: [
        // Two monthly subs (30-day periods), different due dates, same month.
        {
          id: "a",
          due_date: "2099-01-15",
          period_start: "2099-01-15",
          period_end: "2099-02-14",
          expected_amount: "20.00",
          subscription_label: "Veggie",
          status: "PLANNED",
        },
        {
          id: "b",
          due_date: "2099-01-20",
          period_start: "2099-01-20",
          period_end: "2099-02-19",
          expected_amount: "30.00",
          subscription_label: "Eggs",
          status: "PLANNED",
        },
      ],
    });
    renderCard({ memberId: "m1" });

    expect(screen.getByText("members.batch_total")).toBeInTheDocument();
    // Labelled by the MONTH name (dayjs default en in tests), not a date range.
    expect(screen.getByText(/January 2099/)).toBeInTheDocument();
    // 20 + 30 across the month.
    expect(screen.getByText(/50\.00/)).toBeInTheDocument();
    // The "next payment" tag sits on the batch line — exactly once.
    expect(screen.getAllByText("members.next_payment")).toHaveLength(1);
  });

  it("keeps a plain timeline (no batch subtotal) when cycles are mixed", () => {
    chargesHook.mockReturnValue({
      data: [
        // Weekly (7-day period)…
        {
          id: "w",
          due_date: "2099-01-05",
          period_start: "2099-01-05",
          period_end: "2099-01-11",
          expected_amount: "10.00",
          subscription_label: "Veggie",
          status: "PLANNED",
        },
        // …plus monthly (30-day period) → mixed → no recap.
        {
          id: "m",
          due_date: "2099-01-05",
          period_start: "2099-01-05",
          period_end: "2099-02-04",
          expected_amount: "20.00",
          subscription_label: "Eggs",
          status: "PLANNED",
        },
      ],
    });
    renderCard({ memberId: "m1" });

    expect(screen.queryByText("members.batch_total")).not.toBeInTheDocument();
    // Next tag stays on the upcoming row when there is no batch line.
    expect(screen.getByText("members.next_payment")).toBeInTheDocument();
  });

  it("shows no batch subtotal for a pure-weekly member (no period dates)", () => {
    chargesHook.mockReturnValue({
      data: [
        {
          id: "1",
          due_date: "2099-04-06",
          expected_amount: "10.00",
          subscription_label: "Veggie",
          status: "PLANNED",
        },
      ],
    });
    renderCard({ memberId: "m1" });
    expect(screen.queryByText("members.batch_total")).not.toBeInTheDocument();
    // Pure-weekly: the Next tag stays on the upcoming row.
    expect(screen.getByText("members.next_payment")).toBeInTheDocument();
  });

  it("accepts the paginated {results} envelope", () => {
    chargesHook.mockReturnValue({
      data: {
        results: [
          {
            id: "1",
            due_date: "2099-03-01",
            expected_amount: "30.00",
            subscription_label: "X",
            status: "PLANNED",
          },
        ],
      },
    });
    renderCard({ memberId: "m1" });
    expect(screen.getByText(/30\.00/)).toBeInTheDocument();
  });
});
