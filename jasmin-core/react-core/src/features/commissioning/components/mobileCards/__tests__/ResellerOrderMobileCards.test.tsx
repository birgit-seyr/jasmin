/**
 * A reseller's order on the phone: one read-only card per line with the
 * article (its sort, and its size unless M), the amount to pack in the farm's
 * number format, how many PUs that fills, and the line's note.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CommissioningListResellersOrderContent } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) => (typeof fallback === "string" ? fallback : key),
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const numberLocale = vi.hoisted(() => ({ value: "de-DE" }));
vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    getSetting: (key: string, defaultValue?: unknown) => (key === "number_locale" ? numberLocale.value : defaultValue),
  });
  return { useTenant: () => tenant };
});

import { ResellerOrderMobileCards } from "../ResellerOrderMobileCards";

const KG = "commissioning.units.kg";
const PU = "commissioning.pu";

function orderLine(overrides: Partial<CommissioningListResellersOrderContent> = {}): CommissioningListResellersOrderContent {
  return {
    id: "oc-carrots",
    share_article_id: "sa-carrots",
    share_article_name: "Karotten",
    amount: 12.5,
    amount_per_pu: 2.5,
    size: "M",
    unit: "KG",
    sort: "Nantaise",
    note: "",
    ...overrides,
  };
}

const cards = () => Array.from(document.querySelectorAll<HTMLElement>(".mobile-card-item"));

/** Each metric of a card as [label, value, unit]. */
const metrics = (card: HTMLElement) =>
  Array.from(card.querySelectorAll(".mobile-card-metric")).map((metric) => [
    metric.querySelector(".text-muted-xs")?.textContent ?? "",
    metric.querySelector(".mobile-card-metric-value")?.textContent ?? "",
    metric.querySelector(".text-secondary")?.textContent ?? "",
  ]);

const title = (card: HTMLElement) => card.querySelector(".mobile-card-title")?.textContent ?? "";

beforeEach(() => {
  numberLocale.value = "de-DE";
});

describe("ResellerOrderMobileCards", () => {
  it("shows one card per line, in the order's order", () => {
    render(
      <ResellerOrderMobileCards
        lines={[
          orderLine(),
          orderLine({ id: "oc-leeks", share_article_name: "Lauch", sort: null }),
          orderLine({ id: "oc-beets", share_article_name: "Rote Bete", sort: null }),
        ]}
      />,
    );

    expect(cards().map(title)).toEqual(["Karotten Nantaise", "Lauch", "Rote Bete"]);
  });

  it("shows the amount and the PUs it fills, with the PU size, in the farm's number format", () => {
    render(<ResellerOrderMobileCards lines={[orderLine({ amount: 1234.5, amount_per_pu: 2.5 })]} />);

    expect(metrics(cards()[0])).toEqual([
      ["commissioning.amount", "1.234,5", KG],
      [PU, "493,8", `(2,50 ${KG}/${PU})`],
    ]);
  });

  it("follows another number locale", () => {
    numberLocale.value = "en-US";
    render(<ResellerOrderMobileCards lines={[orderLine({ amount: 1234.5, amount_per_pu: 2.5 })]} />);

    expect(metrics(cards()[0])).toEqual([
      ["commissioning.amount", "1,234.5", KG],
      [PU, "493.8", `(2.50 ${KG}/${PU})`],
    ]);
  });

  it("names the size unless it is the default M", () => {
    render(
      <ResellerOrderMobileCards
        lines={[orderLine({ size: "L" }), orderLine({ id: "oc-2", size: "M" }), orderLine({ id: "oc-3", size: "", sort: null })]}
      />,
    );

    expect(cards().map(title)).toEqual(["Karotten Nantaise, commissioning.large", "Karotten Nantaise", "Karotten"]);
  });

  it("leaves the PU metric out when the line has no PU size", () => {
    render(
      <ResellerOrderMobileCards
        lines={[orderLine({ amount_per_pu: 0 }), orderLine({ id: "oc-2", amount_per_pu: undefined as unknown as number })]}
      />,
    );

    for (const card of cards()) {
      expect(metrics(card)).toEqual([["commissioning.amount", "12,5", KG]]);
    }
  });

  it("shows a dash for an amount that isn't a number", () => {
    render(<ResellerOrderMobileCards lines={[orderLine({ amount: undefined as unknown as number })]} />);

    expect(metrics(cards()[0])).toEqual([["commissioning.amount", "-", KG]]);
  });

  it("labels the unit, and shows a unit it doesn't know as it is", () => {
    render(
      <ResellerOrderMobileCards
        lines={[orderLine({ unit: "PCS", amount_per_pu: 0 }), orderLine({ id: "oc-2", unit: "CRATE", amount_per_pu: 0 })]}
      />,
    );

    expect(metrics(cards()[0])[0][2]).toBe("commissioning.units.pcs");
    expect(metrics(cards()[1])[0][2]).toBe("CRATE");
  });

  it("shows the line's note only when it has one", () => {
    render(
      <ResellerOrderMobileCards lines={[orderLine({ note: "Ohne Grün" }), orderLine({ id: "oc-2", note: "" })]} />,
    );

    expect(screen.getByText("Ohne Grün")).toBeInTheDocument();
    expect(cards()[1].querySelector(".text-meta")).toBeNull();
  });

  it("is read-only: no card is a button", () => {
    render(<ResellerOrderMobileCards lines={[orderLine()]} />);

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders an empty list for an order without lines", () => {
    render(<ResellerOrderMobileCards lines={[]} />);

    expect(cards()).toEqual([]);
    expect(document.querySelector(".reseller-order-mobile-cards")).toBeInTheDocument();
  });
});
