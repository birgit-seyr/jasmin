/**
 * useHarvestingListData: the harvesting list's rows, as the table, the phone
 * cards and the PDF show them.
 *
 * The Total cell writes an amount at its unit's precision — kilograms at two
 * decimals, every other unit at one — followed by the packaging units it
 * fills. Rounded up to full PUs, the amount is the full PUs times the amount
 * per PU, and the PU count is a whole number that binary floating-point noise
 * in that division must not push one PU higher.
 *
 * The generated summary query is the mocking boundary; the days, delivery days
 * and variation totals around it are stubbed out, since the rows don't read
 * them. Numbers are formatted in the default German format.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("../../../../test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const summaryRows = vi.hoisted(() => ({ current: [] as unknown[] }));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  getCommissioningDocumentationSummarySummaryRetrieveQueryKey: () => [
    "summary",
  ],
  useCommissioningDocumentationSummarySummaryRetrieve: () => ({
    data: summaryRows.current,
    isLoading: false,
    isFetching: false,
  }),
}));

vi.mock("../useCurrentDays", () => ({
  useCurrentDays: () => ({ getRelatedDays: {}, isLoaded: false }),
}));
vi.mock("../useShareDeliveryDays", () => ({
  useShareDeliveryDays: () => ({ shareDeliveryDays: [] }),
}));
vi.mock("../useAggregatedVariationsTotals", () => ({
  useAggregatedVariationsTotals: () => ({ entries: [] }),
}));

import { useHarvestingListData } from "../useHarvestingListData";

const KG = "commissioning.units.kg";
const PCS = "commissioning.units.pcs";
const PU = "commissioning.pu";

function summaryRow(
  id: string,
  unit: string,
  planned: string,
  amountPerPu: string,
) {
  return {
    id,
    share_article_name: id,
    unit,
    amount_per_pu: amountPerPu,
    theoretical_harvest_amount: planned,
    theoretical_current_stock: "0",
    additional_theoretical_harvest_amount: "0",
    theoretical_harvest_amount_share_content: planned,
    theoretical_current_stock_share_content: "0",
    additional_theoretical_harvest_amount_share_content: "0",
    harvesting_crate_name: "E2",
  };
}

function renderRows(rows: unknown[], roundUpToFullPU: boolean) {
  summaryRows.current = rows;
  const queryClient = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(
    () =>
      useHarvestingListData({
        selectedYear: 2026,
        selectedWeek: 41,
        selectedDay: 2,
        fallbackWeek: 41,
        isPast: false,
        isGardenerView: false,
        roundUpToFullPU,
      }),
    { wrapper },
  );
  return result.current;
}

const totalOf = (rows: Record<string, unknown>[], id: string, suffix = "") =>
  rows.find((row) => row.id === id)?.[`computed_amount_combined${suffix}`];

describe("useHarvestingListData — the Total cell", () => {
  it("writes the total at the unit's precision, next to its PUs", () => {
    const { filteredData } = renderRows(
      [
        summaryRow("carrots", "KG", "20.3", "5"),
        summaryRow("pumpkins", "PCS", "12.5", "4"),
      ],
      false,
    );

    expect(totalOf(filteredData, "carrots")).toBe(`20,30 ${KG} - 4,1 ${PU}`);
    expect(totalOf(filteredData, "carrots", "_share_content")).toBe(
      `20,30 ${KG} - 4,1 ${PU}`,
    );
    expect(totalOf(filteredData, "pumpkins")).toBe(`12,5 ${PCS} - 3,1 ${PU}`);
  });

  it("writes the rounded-up total at the unit's precision and the PUs whole", () => {
    const { filteredData, pdfData } = renderRows(
      [
        summaryRow("carrots", "KG", "20.3", "4.5"),
        summaryRow("pumpkins", "PCS", "12.5", "2.5"),
      ],
      true,
    );

    expect(totalOf(filteredData, "carrots")).toBe(`22,50 ${KG} - 5 ${PU}`);
    expect(totalOf(filteredData, "pumpkins")).toBe(`12,5 ${PCS} - 5 ${PU}`);
    // The PDF prints the same text the table shows.
    expect(totalOf(pdfData, "carrots")).toBe(`22,50 ${KG} - 5 ${PU}`);
  });

  it("doesn't let floating-point noise round a full PU up to one more", () => {
    // 2.1 / 0.3 is 7.000000000000001 in binary floating point, and 3 PUs of
    // 0.1 come to 0.30000000000000004, which divides back into 3.0000000000000004.
    const { filteredData, crateSummary } = renderRows(
      [
        summaryRow("herbs", "KG", "2.1", "0.3"),
        summaryRow("cress", "KG", "0.25", "0.1"),
      ],
      true,
    );

    expect(totalOf(filteredData, "herbs")).toBe(`2,10 ${KG} - 7 ${PU}`);
    expect(totalOf(filteredData, "cress")).toBe(`0,30 ${KG} - 3 ${PU}`);
    expect(filteredData.find((row) => row.id === "cress")).toMatchObject({
      computed_total_amount: 0.3,
      computed_amount_pu: 3,
    });
    expect(crateSummary).toEqual([
      { key: "E2", crate_name: "E2", quantity: 10 },
    ]);
  });
});
