/**
 * PlanningShareContentBase: the per-week harvest-share planner, a
 * (delivery day × share-type variation) grid with summary rows, a buy-in cost
 * total and bulk finalize.
 *
 * Every page hook is real (axes, granularity, summary rows, column builders);
 * the generated API client is the mocking boundary and returns module-level
 * constants, the way a settled TanStack query hands back the same data object
 * on every render. EditableTable, the backup modal, the add-article entry and
 * the selectors are stubs.
 */

import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Form } from "antd";
import dayjs from "dayjs";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShareTypeEnum } from "@shared/api/generated/models";
import type {
  EditableTableProps,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { flushMicrotasks, profileRenders } from "@/test/profileRenders";

// ── Mocks ───────────────────────────────────────────────────────────────────

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
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

// ``useRoles`` is real; it reads the roles of the logged-in user from here.
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { roles: ["office"] } }),
}));

const api = vi.hoisted(() => ({
  planningList: vi.fn(),
  variationsList: vi.fn(),
  refetchGranularity: vi.fn(),
}));

// Ids carry no underscore: the planning cell keys use "_" as the delimiter.
const DELIVERY_DAYS = [
  {
    id: "dtue",
    day_number: 1,
    valid_from: "2026-01-05",
    number_of_tours: 1,
    used_tours: [1],
    delivery_stations: [
      { id: "stmarket", short_name: "Market", tour_number: 1, stop_order: 1 },
    ],
  },
];
const VARIATIONS = [
  { id: "vsmall", size: "S", sort_order: 1, share_type: "harvest", valid_from: "2026-01-05" },
  { id: "vlarge", size: "L", sort_order: 2, share_type: "harvest", valid_from: "2026-01-05" },
];
const SHARE_ARTICLES = [
  {
    id: "art-carrot",
    name: "Carrots",
    default_movement_unit: "KG",
    kg_per_piece_M: "0.150",
    net_price_for_boxes_pieces: "0.40",
  },
  {
    id: "art-apple",
    name: "Apples commissioning.purchased_name_suffix",
    default_movement_unit: "KG",
    is_purchased: true,
  },
];
// Subscribers per (day, variation) this week.
const SUBSCRIBER_COUNTS = {
  "day_dtue_variation_vsmall": 10,
  "day_dtue_variation_vlarge": 4,
};
// Per-share amounts. 10 * 0.5 kg + 4 * 1 kg = 9 kg of bought-in apples.
const PLANNING_ROWS = [
  {
    id: "row-carrot",
    share_article: "art-carrot",
    share_article_name: "Carrots",
    unit: "KG",
    size: "M",
    price_per_unit: "1.10",
    "day_dtue_variation_vsmall": 0.3,
    "day_dtue_variation_vlarge": 0.6,
  },
  {
    id: "row-apple",
    share_article: "art-apple",
    share_article_name: "Apples commissioning.purchased_name_suffix",
    unit: "KG",
    size: "M",
    price_per_unit: "2.00",
    "day_dtue_variation_vsmall": 0.5,
    "day_dtue_variation_vlarge": 1,
  },
];
const GRANULARITY = { days_ok: true, tours_ok: true };
// A tour-planned week: Tuesday runs tours 1 and 2, Friday's station carries no
// tour number (the backend sends ``used_tours: null`` for it).
const TOUR_WEEK_DAYS = [
  { ...DELIVERY_DAYS[0], number_of_tours: 2, used_tours: [1, 2] },
  {
    id: "dfri",
    day_number: 4,
    valid_from: "2026-01-05",
    number_of_tours: 1,
    used_tours: null,
    delivery_stations: [
      { id: "stfarm", short_name: "Farm", tour_number: null, stop_order: 1 },
    ],
  },
];
const TOUR_GRANULARITY = { days_ok: false, tours_ok: true };
const EMPTY: unknown[] = [];

const settled = (data: unknown) => ({
  data,
  isLoading: false,
  isFetching: false,
  error: null,
  refetch: vi.fn(),
});
const SETTLED_DAYS = settled(DELIVERY_DAYS);
const SETTLED_ARTICLES = settled(SHARE_ARTICLES);
const SETTLED_EMPTY = settled(EMPTY);
const SETTLED_COUNTS = settled(SUBSCRIBER_COUNTS);
const SETTLED_AVERAGES = settled({});
const IDLE = settled(undefined);
const SETTLED_TOUR_WEEK_DAYS = settled(TOUR_WEEK_DAYS);

// The week the page loads; tests switch to the tour-planned week.
const week = vi.hoisted(() => ({ tourPlanned: false }));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningSharesDeliveryDaysList: () =>
    week.tourPlanned ? SETTLED_TOUR_WEEK_DAYS : SETTLED_DAYS,
  useCommissioningShareTypeVariationsList: (params: unknown, options: unknown) =>
    api.variationsList(params, options),
  useCommissioningHistoricalShareTypeVariationAveragesRetrieve: () =>
    SETTLED_AVERAGES,
  useCommissioningShareArticlesList: () => SETTLED_ARTICLES,
  useCommissioningGranularityRetrieve: () => ({
    data: week.tourPlanned ? TOUR_GRANULARITY : GRANULARITY,
    isLoading: false,
    error: null,
    refetch: api.refetchGranularity,
  }),
  useCommissioningDefaultShareArticlesInShareList: () => SETTLED_EMPTY,
  useCommissioningHarvestSharePlanningList: (params: unknown, options: unknown) =>
    api.planningList(params, options),
  useCommissioningShareTypeVariationAmountsForPlanningRetrieve: () =>
    SETTLED_COUNTS,
  useCommissioningResellersList: () => SETTLED_EMPTY,
  getCommissioningHarvestSharePlanningListQueryKey: (params?: unknown) => [
    "/api/commissioning/harvest_share_planning/",
    ...(params ? [params] : []),
  ],
  commissioningBulkFinalizeShareContentCreate: vi.fn(),
  commissioningBulkUnfinalizeShareContentCreate: vi.fn(),
  commissioningHarvestSharePlanningCreate: vi.fn(),
  commissioningHarvestSharePlanningUpdate: vi.fn(),
  commissioningHarvestSharePlanningDestroy: vi.fn(),
}));

vi.mock("@features/commissioning/modals", () => ({
  BackupModal: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="backup-modal" /> : null,
}));

vi.mock("@features/commissioning/components/AddShareArticleEntry", () => ({
  default: () => <div data-testid="add-share-article" />,
}));

vi.mock("@shared/selectors", () => ({
  WeekSelector: ({
    selectedYear,
    setSelectedYear,
  }: {
    selectedYear: number;
    setSelectedYear: (year: number) => void;
  }) => (
    <button type="button" onClick={() => setSelectedYear(selectedYear - 1)}>
      previous year
    </button>
  ),
  PlanningModeSelector: ({ value }: { value: string }) => (
    <div data-testid="planning-mode">{value}</div>
  ),
}));

// The grid's props from its latest render.
const table = vi.hoisted(() => ({ props: null as unknown }));

vi.mock("@shared/tables", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@shared/tables")>();
  return {
    ...actual,
    EditableTable: (props: EditableTableProps) => {
      table.props = props;
      return (
        <div
          data-testid="planning-grid"
          data-can-edit={String(Boolean(props.permissions?.canEdit))}
        />
      );
    },
  };
});

import PlanningShareContentBase from "../PlanningShareContentBase";

// ── Helpers ─────────────────────────────────────────────────────────────────

const YEAR = dayjs().isoWeekYear();
const WEEK = dayjs().isoWeek();
const SHARE_ARTICLE_FILTERS = { is_vegetable: true };

const planningListKey = (year = YEAR) => [
  "/api/commissioning/harvest_share_planning/",
  {
    year,
    delivery_week: WEEK,
    share_option: ShareTypeEnum.HARVEST_SHARE,
    is_past: year !== YEAR,
  },
];

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function page() {
  return (
    <PlanningShareContentBase
      shareOption={ShareTypeEnum.HARVEST_SHARE}
      shareArticleFilters={SHARE_ARTICLE_FILTERS}
      pageTitle="Harvest share planning"
      explainerKey="explainers.harvest_share_planning"
    />
  );
}

function renderPage() {
  const client = makeQueryClient();
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}>{page()}</QueryClientProvider>);
  return { client, invalidateSpy };
}

function grid(): EditableTableProps {
  if (!table.props) throw new Error("the planning grid never rendered");
  return table.props as EditableTableProps;
}

beforeEach(() => {
  table.props = null;
  week.tourPlanned = false;
  api.refetchGranularity.mockReset();
  api.variationsList.mockReset().mockReturnValue(settled(VARIATIONS));
  const planningResult = settled(PLANNING_ROWS);
  api.planningList
    .mockReset()
    .mockImplementation(
      (_params: unknown, options?: { query?: { enabled?: boolean } }) =>
        options?.query?.enabled === false ? IDLE : planningResult,
    );
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("PlanningShareContentBase (render-loop smoke)", () => {
  it("does not re-render in a loop on mount", async () => {
    const profiler = profileRenders();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        {profiler.wrap(page(), "planning")}
      </QueryClientProvider>,
    );
    await screen.findByTestId("planning-grid");
    await flushMicrotasks(50);

    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});

describe("PlanningShareContentBase", () => {
  it("loads the planning grid of the current week for its share option", () => {
    renderPage();

    expect(api.planningList).toHaveBeenLastCalledWith(planningListKey()[1], {
      query: { enabled: true },
    });
    expect(screen.getByRole("heading", { name: "Harvest share planning" }))
      .toBeInTheDocument();
    expect(grid().initialData).toHaveLength(2);
    // Day and tour granularity both hold, so the plain per-day mode is picked.
    expect(screen.getByTestId("planning-mode")).toHaveTextContent("basic");
  });

  it("shows a configuration hint instead of the grid when the week has no share-type variations", () => {
    api.variationsList.mockReturnValue(settled(EMPTY));
    renderPage();

    expect(
      screen.getByText("commissioning.no_variation_columns_title"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("planning-grid")).not.toBeInTheDocument();
    expect(api.planningList).toHaveBeenLastCalledWith(expect.anything(), {
      query: { enabled: false },
    });
  });

  it("adds up the week's buy-in cost of purchased articles in the tenant's currency", () => {
    renderPage();

    // Only the apples are bought in: 9 kg at 2.00.
    const total = screen.getByText("commissioning.total_purchase_cost_week")
      .nextElementSibling;
    expect(total).toHaveTextContent("18,00 €");
  });

  it("recomputes the buy-in cost from the grid's live rows", () => {
    renderPage();

    act(() => {
      grid().onDataChange?.([
        { ...PLANNING_ROWS[0], key: "row-carrot" },
        { ...PLANNING_ROWS[1], key: "row-apple", price_per_unit: "3.00" },
      ]);
    });

    const total = screen.getByText("commissioning.total_purchase_cost_week")
      .nextElementSibling;
    expect(total).toHaveTextContent("27,00 €");
  });

  it("makes a past week read-only and hides the bulk actions", async () => {
    renderPage();

    await userEvent.click(screen.getByRole("button", { name: "previous year" }));

    expect(api.planningList).toHaveBeenLastCalledWith(
      planningListKey(YEAR - 1)[1],
      { query: { enabled: true } },
    );
    expect(screen.getByText("table.past_week_readonly")).toBeInTheDocument();
    expect(screen.getByTestId("planning-grid")).toHaveAttribute(
      "data-can-edit",
      "false",
    );
    expect(
      screen.queryByRole("button", { name: "commissioning.finalize" }),
    ).not.toBeInTheDocument();
  });

  it("does not let rows scaffolded from a forecast or from stock be deleted", () => {
    renderPage();
    const canDeleteRecord = grid().permissions?.canDeleteRecord as (
      record: TableRecord,
    ) => boolean;

    expect(canDeleteRecord({ key: "row-1", forecast: "fc-1" })).toBe(false);
    expect(
      canDeleteRecord({ key: "row-2", current_stock_begin_of_week: "12.5" }),
    ).toBe(false);
    expect(canDeleteRecord({ key: "row-3" })).toBe(true);
    expect(canDeleteRecord({ key: -1, forecast: "fc-1" })).toBe(true);
  });

  it("saves only the cells of the active planning tier and stamps the week", () => {
    renderPage();

    const payload = grid().customSave!(
      {
        share_article: "art-carrot",
        unit: "KG",
        "day_dtue_variation_vsmall": "",
        "day_dtue_variation_vlarge": "0",
        "day_dtue_variation_vsmall_tour_1": 0.4,
        "day_dtue_variation_vsmall_station_stmarket": 0.4,
        "backup_day_dtue_variation_vsmall": 0.2,
      },
      { key: "row-carrot" },
    );

    expect(payload).toEqual({
      share_article: "art-carrot",
      unit: "KG",
      "day_dtue_variation_vsmall": 0,
      "day_dtue_variation_vlarge": 0,
      "backup_day_dtue_variation_vsmall": 0.2,
      year: YEAR,
      delivery_week: WEEK,
    });
  });

  it("refuses to save a purchased article without a seller", () => {
    renderPage();

    expect(() =>
      grid().customSave!({ share_article: "art-apple" }, { key: -1 }),
    ).toThrow("commissioning.seller_required_for_purchase");
    expect(
      grid().customSave!(
        { share_article: "art-apple", seller: "seller-1" },
        { key: -1 },
      ),
    ).toMatchObject({ seller: "seller-1", year: YEAR });
  });

  it("patches a saved row into the cached list without refetching it", () => {
    const { client, invalidateSpy } = renderPage();
    const key = planningListKey();
    client.setQueryData(key, [
      { ...PLANNING_ROWS[0], "day_dtue_variation_vlarge": 0.6 },
      PLANNING_ROWS[1],
    ]);

    // The response omits the cleared large-share cell.
    act(() => {
      grid().onSaveSuccess?.(
        {
          key: "row-carrot",
          id: "row-carrot",
          share_article_name: "Carrots",
          "day_dtue_variation_vsmall": 0.35,
        },
        "update",
      );
    });

    const cached = client.getQueryData<Record<string, unknown>[]>(key)!;
    expect(cached[0]).toMatchObject({
      id: "row-carrot",
      price_per_unit: "1.10",
      "day_dtue_variation_vsmall": 0.35,
    });
    expect(cached[0]).not.toHaveProperty("day_dtue_variation_vlarge");
    expect(cached[1]).toBe(PLANNING_ROWS[1]);
    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(api.refetchGranularity).toHaveBeenCalled();
  });

  it("refetches the grid when a save clears a row completely", () => {
    const { invalidateSpy } = renderPage();

    act(() => {
      grid().onSaveSuccess?.(
        { key: "row-carrot", id: "row-carrot", variations: {}, basic_variations: {} },
        "update",
      );
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: planningListKey() });
  });

  it("refetches the grid after a delete", () => {
    const { invalidateSpy } = renderPage();

    act(() => grid().onDeleteSuccess?.("row-carrot"));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: planningListKey() });
    expect(api.refetchGranularity).toHaveBeenCalled();
  });
});

describe("PlanningShareContentBase article defaults", () => {
  const changeSize = (values: Record<string, unknown>) => {
    const [form] = renderHook(() => Form.useForm()).result.current;
    form.setFieldsValue(values);
    const size = grid().columns.find((c) => c.key === "size");
    if (!size?.onFieldChange) throw new Error("no size column");
    act(() => {
      size.onFieldChange?.(values.size, { key: -1 }, form, "size");
    });
    return form.getFieldsValue(true);
  };

  it("takes a piece's weight and price from the article for the row's size", () => {
    renderPage();

    expect(
      changeSize({ share_article: "art-carrot", unit: "PCS", size: "M" }),
    ).toMatchObject({ kg_per_piece: "0.150", price_per_unit: "0.40" });
  });

  it("clears the weight for kilos and keeps the price the article has none for", () => {
    renderPage();
    changeSize({ share_article: "art-carrot", unit: "PCS", size: "M" });

    expect(
      changeSize({
        share_article: "art-carrot",
        unit: "KG",
        size: "M",
        kg_per_piece: "0.150",
        price_per_unit: "0.40",
      }),
    ).toMatchObject({ kg_per_piece: null, price_per_unit: "0.40" });
  });

  it("clears the price of a newly picked article that has none for the unit", () => {
    renderPage();

    expect(
      changeSize({ share_article: "art-carrot", unit: "BUNCH", size: "M", price_per_unit: "9.99" }),
    ).toMatchObject({ kg_per_piece: null, price_per_unit: null });
  });
});

describe("PlanningShareContentBase still free", () => {
  const stillFree = (record: TableRecord) => {
    const column = grid().columns.find((c) => c.key === "still_free");
    if (!column?.render) throw new Error("no still-free column");
    return render(<>{column.render(undefined, record, 0)}</>).container;
  };

  it("adds the stock on hand to the forecast before taking off the planned amounts", () => {
    renderPage();

    // 40 kg forecast + 12.5 kg stock − (10 × 0.5 kg + 4 × 1 kg)
    expect(
      stillFree({
        key: "row-carrot",
        unit: "KG",
        forecast_available_amount: "40.00",
        forecast_unit: "KG",
        current_stock_begin_of_week: 12.5,
        "day_dtue_variation_vsmall": 0.5,
        "day_dtue_variation_vlarge": 1,
      }),
    ).toHaveTextContent("43,50");
  });

  it("leaves out a forecast counted in another unit than the row", () => {
    renderPage();

    // 12.5 kg stock − (10 × 0.5 kg + 4 × 1 kg); the 40 pieces stay out.
    expect(
      stillFree({
        key: "row-carrot",
        unit: "KG",
        forecast_available_amount: "40.00",
        forecast_unit: "PCS",
        current_stock_begin_of_week: 12.5,
        "day_dtue_variation_vsmall": 0.5,
        "day_dtue_variation_vlarge": 1,
      }),
    ).toHaveTextContent("3,50");
  });

  it("counts the stock alone for a row without a forecast", () => {
    renderPage();

    expect(
      stillFree({ key: "row-leek", unit: "KG", current_stock_begin_of_week: 3 }),
    ).toHaveTextContent("3,00");
  });
});

describe("PlanningShareContentBase tour planning", () => {
  beforeEach(() => {
    week.tourPlanned = true;
  });

  it("plans a day whose station carries no tour number as a whole day", () => {
    renderPage();

    expect(screen.getByTestId("planning-mode")).toHaveTextContent("tours");
    const friday = grid().columns.find((c) => c.key === "day_dfri")!;
    expect(friday.children?.[0]).toMatchObject({
      dataIndex: "day_dfri_variation_vsmall",
      inputType: "positive_decimal2",
    });
    expect(friday.children?.[0].children).toBeUndefined();
    expect(friday.children?.[1].children).toBeUndefined();
  });

  it("saves the tour cells of a toured day and the whole-day cells of a day without tours", () => {
    renderPage();

    const payload = grid().customSave!(
      {
        share_article: "art-carrot",
        "day_dtue_variation_vsmall": 0.4,
        "day_dtue_variation_vsmall_tour_1": 0.4,
        "day_dtue_variation_vsmall_station_stmarket": 0.4,
        "day_dfri_variation_vsmall": 0.6,
        "day_dfri_variation_vsmall_station_stfarm": 0.6,
      },
      { key: "row-carrot" },
    );

    expect(payload).toEqual({
      share_article: "art-carrot",
      "day_dtue_variation_vsmall_tour_1": 0.4,
      "day_dfri_variation_vsmall": 0.6,
      year: YEAR,
      delivery_week: WEEK,
    });
  });
});
