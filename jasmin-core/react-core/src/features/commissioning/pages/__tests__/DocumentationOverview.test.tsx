/**
 * The documentation overview filters by weekday through ``day_number``.
 * ``delivery_day`` is only a backward-compatible alias the backend still
 * accepts for bundles shipped before the rename, so this page must send the
 * canonical name — and must send the day as a number, not a string.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// The only antd Select on the page is the source picker; the stub exposes its
// onChange so a test can switch to the week-scoped PURCHASE source.
vi.mock("antd", () => ({
  Select: ({ onChange }: { onChange?: (value: string) => void }) => (
    <button data-testid="pick-purchase" onClick={() => onChange?.("PURCHASE")}>
      pick-purchase
    </button>
  ),
}));

const overviewHookMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDocumentationOverviewList: (
    params: unknown,
    opts?: unknown,
  ) => overviewHookMock(params, opts),
}));

// Real year/week state — imported from its own module rather than the
// ``@hooks/index`` barrel, which would drag in the whole shared hook layer.
vi.mock("@hooks/index", async () => {
  const actual = await import("@hooks/useYearWeekState");
  return {
    useYearWeekState: actual.useYearWeekState,
    currentWeek: actual.currentWeek,
  };
});

vi.mock("@features/commissioning/hooks", () => ({
  useShareArticleColumn: () => ({
    shareArticleColumn: { key: "share_article", dataIndex: "share_article" },
  }),
  useAmountUnitSizeColumns: () => ({ amountUnitSizeColumns: [] }),
}));

// The two filters the test drives: each stub exposes a button that fires the
// setter the page passed down.
vi.mock("@shared/selectors", () => ({
  WeekSelector: () => <div data-testid="week-selector" />,
  DaySelector: ({
    setSelectedDay,
  }: {
    setSelectedDay: (day: number | null) => void;
  }) => (
    <button data-testid="pick-day" onClick={() => setSelectedDay(2)}>
      pick-day
    </button>
  ),
}));

vi.mock("@features/commissioning/selectors", () => ({
  ShareArticleSelector: ({
    setSelectedShareArticle,
  }: {
    setSelectedShareArticle: (value: string | null) => void;
  }) => (
    <button
      data-testid="pick-article"
      onClick={() => setSelectedShareArticle("art-1")}
    >
      pick-article
    </button>
  ),
}));

vi.mock("@shared/tables", () => ({
  READ_ONLY_PERMISSION: {},
  EditableTable: ({
    initialData,
  }: {
    initialData?: Array<Record<string, unknown>>;
  }) => <span data-testid="row-count">{(initialData ?? []).length}</span>,
}));

vi.mock("@shared/ui", () => ({
  ExplainerText: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="explainer">{children}</div>
  ),
}));

import DocumentationOverview from "../DocumentationOverview";

beforeEach(() => {
  overviewHookMock.mockReset().mockReturnValue({
    data: [{ share_article_name: "Karotten", amount: 3 }],
    isFetching: false,
  });
});

function lastParams(): Record<string, unknown> {
  const calls = overviewHookMock.mock.calls;
  return calls[calls.length - 1][0] as Record<string, unknown>;
}

describe("DocumentationOverview — day filter", () => {
  it("sends the chosen weekday as a numeric day_number, not the delivery_day alias", async () => {
    render(<DocumentationOverview />);
    await userEvent.click(screen.getByTestId("pick-article"));
    await userEvent.click(screen.getByTestId("pick-day"));

    expect(lastParams().day_number).toBe(2);
    expect(lastParams()).not.toHaveProperty("delivery_day");
  });

  it("omits the day filter entirely while no day is chosen", async () => {
    render(<DocumentationOverview />);
    await userEvent.click(screen.getByTestId("pick-article"));

    expect(lastParams()).not.toHaveProperty("day_number");
    expect(lastParams()).not.toHaveProperty("delivery_day");
  });

  it("drops the day filter and hides the picker for week-scoped purchases", async () => {
    render(<DocumentationOverview />);
    await userEvent.click(screen.getByTestId("pick-article"));
    await userEvent.click(screen.getByTestId("pick-day"));
    expect(lastParams().day_number).toBe(2);

    await userEvent.click(screen.getByTestId("pick-purchase"));

    // Purchases carry no weekday, so a day filter would empty the table
    // instead of narrowing it.
    expect(lastParams().source).toBe("PURCHASE");
    expect(lastParams()).not.toHaveProperty("day_number");
    expect(screen.queryByTestId("pick-day")).not.toBeInTheDocument();
  });

  it("gates the query on a chosen share article", () => {
    render(<DocumentationOverview />);
    const [, opts] = overviewHookMock.mock.calls[0];
    expect((opts as { query: { enabled: boolean } }).query.enabled).toBe(false);
  });
});
