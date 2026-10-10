/**
 * ``has_orders_without_invoice`` is a real backend query param on the
 * resellers list, so the selector has to forward it verbatim — and must keep
 * omitting it for the pages that want every reseller, since sending ``false``
 * is not "no filter" but "only resellers with nothing left to invoice".
 *
 * antd Select is stubbed: what's under test is the params object handed to
 * the generated list hook, not the rendered widget.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("antd", () => ({
  Select: ({
    className,
    style,
    value,
    placeholder,
    options = [],
  }: {
    className?: string;
    style?: object;
    value?: unknown;
    placeholder?: string;
    options?: { value: unknown; label: React.ReactNode }[];
  }) => (
    <div data-testid="select" className={className} style={style}>
      {options.find((option) => option.value === value)?.label ?? placeholder}
    </div>
  ),
}));

const listHookMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningResellersList: (params: unknown) => listHookMock(params),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import ResellerSelector from "../ResellerSelector";

beforeEach(() => {
  listHookMock.mockReset().mockReturnValue({ data: [], isLoading: false });
});

function renderSelector(props: Record<string, unknown> = {}) {
  return render(
    <ResellerSelector
      selectedReseller={null}
      setSelectedReseller={() => {}}
      {...props}
    />,
  );
}

function lastParams(): Record<string, unknown> {
  const calls = listHookMock.mock.calls;
  return calls[calls.length - 1][0] as Record<string, unknown>;
}

describe("ResellerSelector — has_orders_without_invoice", () => {
  it("forwards the filter to the resellers list query", () => {
    renderSelector({ has_orders_without_invoice: true });
    expect(lastParams().has_orders_without_invoice).toBe(true);
  });

  it("omits the filter entirely when it isn't requested", () => {
    renderSelector();
    expect(lastParams()).not.toHaveProperty("has_orders_without_invoice");
  });

  it("keeps the reseller role flags alongside the filter", () => {
    renderSelector({ has_orders_without_invoice: true });
    expect(lastParams()).toMatchObject({
      is_reseller: true,
      is_active_reseller: true,
    });
  });

  it("scopes to sellers without the filter when userType is seller", () => {
    renderSelector({ userType: "seller" });
    expect(lastParams()).toMatchObject({
      is_seller: true,
      is_active_seller: true,
    });
    expect(lastParams()).not.toHaveProperty("has_orders_without_invoice");
  });
});

describe("ResellerSelector — look", () => {
  it("takes a reseller select's width from the stylesheet", () => {
    renderSelector();
    const select = screen.getByTestId("select");
    expect(select).toHaveClass("bold-select", "week-selector-select", "reseller-selector");
    expect(select).not.toHaveClass("reseller-selector--seller");
    expect(select).not.toHaveAttribute("style");
  });

  it("indents a seller select through the stylesheet", () => {
    renderSelector({ userType: "seller" });
    expect(screen.getByTestId("select")).toHaveClass("reseller-selector", "reseller-selector--seller");
  });
});

describe("ResellerSelector — all resellers", () => {
  it("shows 'all resellers' as the pick while it is picked", () => {
    listHookMock.mockReturnValue({
      data: [{ id: "res-1", company_name: "Bistro Blau" }],
      isLoading: false,
    });
    renderSelector({ include_null_option: true });

    expect(screen.getByTestId("select")).toHaveTextContent("commissioning.all_resellers");
  });

  it("shows the placeholder while nothing is picked and no 'all' entry is offered", () => {
    renderSelector();

    expect(screen.getByTestId("select")).toHaveTextContent("placeholder.reseller_selector");
  });
});
