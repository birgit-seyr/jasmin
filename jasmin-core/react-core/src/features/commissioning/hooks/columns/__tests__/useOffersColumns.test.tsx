/**
 * useOffersColumns: which cells of an offer stay editable once it is published.
 * A published offer lets only its available amount change, which the office
 * corrects as stock turns up or goes off. The washing/cleaning and note column
 * hooks are real; the other column hooks and the data hooks are stubbed.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));
vi.mock("@hooks/configuration/useCurrency", () => ({
  useCurrency: () => ({ currencySymbol: "€", formatCurrency: String }),
}));
vi.mock("@hooks/useNumberFormat", () => ({
  useNumberFormat: () => ({
    format: (value: number, digits: number) => value.toFixed(digits),
  }),
}));
vi.mock("../../useCrates", () => ({ useCrates: () => ({ crates: [] }) }));
vi.mock("../../useOfferTiers", () => ({ useOfferTiers: () => [1, 5, 10] }));
vi.mock("../useFinalColumn", () => ({
  useFinalColumn: () => ({
    finalColumn: { key: "is_finalized", dataIndex: "is_finalized" },
  }),
}));
vi.mock("../useShareArticleColumn", () => ({
  useShareArticleColumn: () => ({
    shareArticleColumn: { key: "share_article", dataIndex: "share_article" },
    handleUnitChange: vi.fn(),
  }),
}));
vi.mock("../useAmountUnitSizeColumns", () => ({
  useAmountUnitSizeColumns: () => ({ amountUnitSizeColumns: [] }),
}));

import { useOffersColumns } from "../useOffersColumns";

function column(dataIndex: string): EditableColumnConfig<TableRecord> {
  const { result } = renderHook(() =>
    useOffersColumns({
      shareArticleFilters: {
        is_active: true,
        is_sold_to_resellers: true,
        get_price_info: true,
        price_date: "2026-10-12",
      },
      shareArticles: [],
      currentOfferGroup: undefined,
      selectedOfferGroup: "og-1",
    }),
  );
  const found = result.current.columns
    .flatMap((col) => col.children ?? [col])
    .find((col) => col.dataIndex === dataIndex);
  if (!found) throw new Error(`no ${dataIndex} column`);
  return found;
}

function isLocked(dataIndex: string, record: TableRecord): boolean {
  const { disabled } = column(dataIndex);
  return typeof disabled === "function" ? disabled(record) : Boolean(disabled);
}

const published = { key: "offer-1", is_finalized: true, amount_ordered: "0.000" };
const draft = { key: "offer-1", is_finalized: false, amount_ordered: "0.000" };

describe("useOffersColumns on a published offer", () => {
  it("keeps the available amount editable", () => {
    expect(isLocked("amount", published)).toBe(false);
  });

  it.each([
    "price_1",
    "price_2",
    "price_3",
    "sort",
    "description",
    "amount_per_pu",
    "used_crate_name",
    "washing",
    "cleaning",
    "comes_from_long_term_storage",
    "note",
  ])("locks %s, which stays as published", (dataIndex) => {
    expect(isLocked(dataIndex, published)).toBe(true);
    expect(isLocked(dataIndex, draft)).toBe(false);
  });
});
