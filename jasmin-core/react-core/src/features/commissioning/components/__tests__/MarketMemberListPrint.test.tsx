/**
 * MarketMemberListPrint: the market's member list, fetched on click — the
 * cooperative's current members by last name.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import dayjs from "dayjs";
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

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({});
  return { useTenant: () => tenant };
});

const { membersList, generator } = vi.hoisted(() => ({
  membersList: vi.fn(),
  generator: { props: null as Record<string, unknown> | null },
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  getCommissioningMembersListQueryOptions: (params: unknown) => ({
    queryKey: ["/api/commissioning/members/", params],
    queryFn: async () => membersList(params),
  }),
}));

vi.mock("@features/commissioning/pdfs", () => ({
  MarketMemberListPDFGenerator: (props: Record<string, unknown>) => {
    generator.props = props;
    return null;
  },
}));

import MarketMemberListPrint from "../MarketMemberListPrint";

const today = dayjs().format("YYYY-MM-DD");
const yesterday = dayjs().subtract(1, "day").format("YYYY-MM-DD");
const tomorrow = dayjs().add(1, "day").format("YYYY-MM-DD");

function member(overrides: Record<string, unknown>) {
  return {
    id: "m",
    first_name: "Jana",
    last_name: "Abel",
    company_name: null,
    member_number: 1,
    admin_confirmed: true,
    cancelled_effective_at: null,
    ...overrides,
  };
}

type Loaded = {
  members: { id: string; last_name: string; first_name: string; member_number: number }[];
  asOf: string;
};

function renderAndLoad() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MarketMemberListPrint />
    </QueryClientProvider>,
  );
  const load = generator.props?.loadDocumentProps as () => Promise<Loaded>;
  return load();
}

beforeEach(() => {
  membersList.mockReset();
  generator.props = null;
});

describe("MarketMemberListPrint", () => {
  it("fetches nothing until the list is printed", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MarketMemberListPrint />
      </QueryClientProvider>,
    );

    expect(generator.props?.buttonText).toBe("commissioning.market_member_list_pdf");
    expect(membersList).not.toHaveBeenCalled();
  });

  it("lists the confirmed, numbered members who haven't left, by last name", async () => {
    membersList.mockResolvedValue([
      member({ id: "zahn", last_name: "Zahn", member_number: 3 }),
      member({ id: "oertel", last_name: "Örtel", member_number: 7 }),
      member({ id: "pending", last_name: "Pending", admin_confirmed: false }),
      member({ id: "unnumbered", last_name: "Unnumbered", member_number: null }),
      member({ id: "left", last_name: "Left", cancelled_effective_at: yesterday }),
      member({ id: "leaving", last_name: "Leaving", cancelled_effective_at: tomorrow }),
      // The exit day itself is still a member's.
      member({ id: "today", last_name: "Today", cancelled_effective_at: today }),
      member({ id: "bauer-tom", last_name: "Bauer", first_name: "Tom", member_number: 9 }),
      member({ id: "bauer-eva", last_name: "Bauer", first_name: "Eva", member_number: 8 }),
      member({ id: "farm", first_name: null, last_name: null, company_name: "Hofladen", member_number: 5 }),
    ]);

    const loaded = await renderAndLoad();

    expect(membersList).toHaveBeenCalledWith({ is_active: true });
    expect(loaded.members.map((row) => row.id)).toEqual([
      "bauer-eva",
      "bauer-tom",
      "farm",
      "leaving",
      "oertel",
      "today",
      "zahn",
    ]);
    expect(loaded.members.find((row) => row.id === "farm")).toEqual({
      id: "farm",
      last_name: "Hofladen",
      first_name: "",
      member_number: 5,
    });
    expect(loaded.asOf).toBe(dayjs().format("DD.MM.YYYY"));
  });
});
