/**
 * VariationsTotalsCard: the per-size share totals for the selected delivery
 * day(s). It fetches one totals request per delivery day, sums them per
 * variation, labels each row with its share type and orders the rows by share
 * type, then by the variation's sort order. The generated client is the
 * mocking boundary.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ShareTypeVariation,
  ShareTypeVariationTotalRow,
} from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const server = vi.hoisted(() => ({
  totalsByDay: {} as Record<string, ShareTypeVariationTotalRow[]>,
  variations: [] as Partial<ShareTypeVariation>[],
  totalsRequests: [] as Record<string, unknown>[],
}));

vi.mock(
  "@shared/api/generated/commissioning/commissioning",
  async (importOriginal) => ({
    ...(await importOriginal<
      typeof import("@shared/api/generated/commissioning/commissioning")
    >()),
    getCommissioningShareTypeVariationsTotalsRetrieveQueryOptions: (
      params: Record<string, unknown>,
    ) => ({
      queryKey: ["variation-totals", params],
      queryFn: async () => {
        server.totalsRequests.push(params);
        return {
          variations: server.totalsByDay[String(params.delivery_day)] ?? [],
        };
      },
    }),
    useCommissioningShareTypeVariationsList: () => ({
      data: server.variations,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    }),
  }),
);

import VariationsTotalsCard from "../VariationsTotalsCard";

const row = (
  id: string,
  size: string,
  total_quantity: number,
): ShareTypeVariationTotalRow => ({
  share__share_type_variation_id: id,
  share__share_type_variation__size: size,
  total_quantity,
});

const renderCard = (props: Parameters<typeof VariationsTotalsCard>[0]) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <VariationsTotalsCard {...props} />
    </QueryClientProvider>,
  );
};

const listedRows = () =>
  screen.queryAllByRole("listitem").map((item) => item.textContent);

beforeEach(() => {
  server.totalsByDay = {};
  server.variations = [
    { id: "veg-m", size: "M", share_type_name: "Vegetables", sort_order: 2 },
    { id: "veg-s", size: "S", share_type_name: "Vegetables", sort_order: 1 },
    { id: "bread-l", size: "L", share_type_name: "Bread", sort_order: 1 },
  ];
  server.totalsRequests = [];
});

describe("VariationsTotalsCard", () => {
  it("sums each variation across every delivery day it is given", async () => {
    server.totalsByDay = {
      "day-tue": [row("veg-s", "S", 12), row("veg-m", "M", 7)],
      "day-fri": [row("veg-s", "S", 5), row("bread-l", "L", 3)],
    };

    renderCard({
      filters: { year: 2026, delivery_week: 41, delivery_day: ["day-tue", "day-fri"] },
    });

    await waitFor(() => expect(listedRows()).toHaveLength(3));
    expect(listedRows()).toEqual([
      "Bread commissioning.L: 3",
      "Vegetables commissioning.S: 17",
      "Vegetables commissioning.M: 7",
    ]);
    expect(server.totalsRequests).toEqual([
      { year: 2026, delivery_week: 41, delivery_day: "day-tue" },
      { year: 2026, delivery_week: 41, delivery_day: "day-fri" },
    ]);
  });

  it("asks for a delivery day given with its own week in that week", async () => {
    server.totalsByDay = {
      "day-sat": [row("veg-s", "S", 4)],
      "day-mon": [row("veg-s", "S", 6)],
    };

    renderCard({
      filters: {
        year: 2026,
        delivery_week: 53,
        delivery_day: [
          "day-sat",
          { id: "day-mon", year: 2027, delivery_week: 1 },
        ],
      },
    });

    await waitFor(() => expect(listedRows()).toEqual(["Vegetables commissioning.S: 10"]));
    expect(server.totalsRequests).toEqual([
      { year: 2026, delivery_week: 53, delivery_day: "day-sat" },
      { year: 2027, delivery_week: 1, delivery_day: "day-mon" },
    ]);
  });

  it("orders a share type's sizes by their sort order, not by the API's order", async () => {
    server.totalsByDay = {
      "day-tue": [row("veg-m", "M", 4), row("veg-s", "S", 9)],
    };

    renderCard({ filters: { year: 2026, delivery_week: 41, delivery_day: "day-tue" } });

    await waitFor(() => expect(listedRows()).toHaveLength(2));
    expect(listedRows()).toEqual([
      "Vegetables commissioning.S: 9",
      "Vegetables commissioning.M: 4",
    ]);
  });

  it("hides sizes with nothing to deliver unless hideZero is off", async () => {
    server.totalsByDay = {
      "day-tue": [row("veg-s", "S", 0), row("veg-m", "M", 6)],
    };
    const filters = { year: 2026, delivery_week: 41, delivery_day: "day-tue" };

    const { unmount } = renderCard({ filters });
    await waitFor(() => expect(listedRows()).toHaveLength(1));
    expect(listedRows()).toEqual(["Vegetables commissioning.M: 6"]);
    unmount();

    renderCard({ filters, hideZero: false });
    await waitFor(() => expect(listedRows()).toHaveLength(2));
    expect(listedRows()).toEqual([
      "Vegetables commissioning.S: 0",
      "Vegetables commissioning.M: 6",
    ]);
  });

  it("leaves out the share-type label of a variation it has no record of", async () => {
    server.totalsByDay = { "day-tue": [row("unknown", "XL", 2)] };

    renderCard({ filters: { year: 2026, delivery_week: 41, delivery_day: "day-tue" } });

    await waitFor(() => expect(listedRows()).toEqual(["commissioning.XL: 2"]));
  });

  it("shows the empty text and fetches nothing until a week and a day are chosen", () => {
    const { container } = renderCard({
      filters: { year: 2026, delivery_week: null, delivery_day: "day-tue" },
      title: "Shares this week",
      emptyText: "No shares packed",
      className: "harvest-totals",
    });

    expect(screen.getByText("Shares this week")).toBeInTheDocument();
    expect(screen.getByText("No shares packed")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(container.firstChild).toHaveClass("variations-totals-card", "harvest-totals");
    expect(server.totalsRequests).toEqual([]);
  });

  it("falls back to the default title and empty text, with a tooltip icon when given one", () => {
    renderCard({ tooltip: "Counted per size" });

    expect(screen.getByText("commissioning.variations_totals")).toBeInTheDocument();
    expect(screen.getByText("common.no_data")).toBeInTheDocument();
    const header = screen
      .getByText("commissioning.variations_totals")
      .closest(".variations-totals-card-header") as HTMLElement;
    expect(within(header).getByLabelText("Counted per size")).toBeInTheDocument();
  });
});
