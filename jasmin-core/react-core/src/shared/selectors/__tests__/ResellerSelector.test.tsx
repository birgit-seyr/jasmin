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

interface StubOption {
  value: unknown;
  label: React.ReactNode;
  className?: string;
}

interface StubSelectProps {
  className?: string;
  style?: object;
  value?: unknown;
  placeholder?: string;
  options?: StubOption[];
  showSearch?: boolean;
  filterOption?: (input: string, option?: StubOption) => boolean;
}

const selectPropsMock = vi.fn();
vi.mock("antd", () => ({
  Select: (props: StubSelectProps) => {
    selectPropsMock(props);
    const { className, style, value, placeholder, options = [] } = props;
    return (
      <div data-testid="select" className={className} style={style}>
        {options.find((option) => option.value === value)?.label ?? placeholder}
      </div>
    );
  },
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
  selectPropsMock.mockReset();
});

function lastSelectProps(): StubSelectProps {
  const calls = selectPropsMock.mock.calls;
  return calls[calls.length - 1][0] as StubSelectProps;
}

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

describe("ResellerSelector — options", () => {
  const resellers = [
    { id: "res-3", company_name: "bistro Blau", has_orders: false },
    { id: "res-2", company_name: "Zur Linde", first_name: "Erika", last_name: "Muster", has_orders: true },
    { id: "res-4", company_name: "Bistro Blau", has_orders: true },
    { id: "res-1", company_name: "Alte Mühle", first_name: "Max" },
  ];

  beforeEach(() => {
    listHookMock.mockReturnValue({ data: resellers, isLoading: false });
  });

  it("labels each option with its name as plain text, sorted by that name and then by id", () => {
    renderSelector({ include_null_option: true });

    expect(lastSelectProps().options?.map(({ value, label }) => ({ value, label }))).toEqual([
      { value: "__base-entity-selector-null__", label: "commissioning.all_resellers" },
      { value: "res-1", label: "Alte Mühle - Max" },
      { value: "res-3", label: "bistro Blau" },
      { value: "res-4", label: "Bistro Blau" },
      { value: "res-2", label: "Zur Linde - Erika - Muster" },
    ]);
  });

  it("marks the resellers with orders through the option's class", () => {
    renderSelector();

    const classes = Object.fromEntries(
      (lastSelectProps().options ?? []).map((option) => [option.value, option.className]),
    );
    expect(classes).toEqual({
      "res-1": "without-orders",
      "res-2": "with-orders",
      "res-3": "without-orders",
      "res-4": "with-orders",
    });
  });

  it("is searchable by the displayed name, ignoring case", () => {
    renderSelector();

    const { showSearch, filterOption, options = [] } = lastSelectProps();
    expect(showSearch).toBe(true);
    const matches = options
      .filter((option) => filterOption?.("LINDE", option))
      .map((option) => option.value);
    expect(matches).toEqual(["res-2"]);
  });
});
