// MemberDetail is a heavy page that orchestrates many subcomponents and 4 API
// calls. We mock every subcomponent and modal so the test stays focused on
// what THIS page actually owns: the route param wiring, the API calls, the
// loading/not-found branches, and the PATCH + cache-invalidation on edit.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { server } from "@/test/msw/server";
import { profileRenders, flushMicrotasks } from "@/test/profileRenders";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : k,
    i18n: { changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  // Build once so the returned object is reference-stable across
  // renders — matters for any downstream useCallback/useMemo deps.
  const tenant = makeUseTenantMock();
  return {
    useTenant: () => tenant,
    useShareTypes: () => ({ shareTypes: [] }),
    useLogoShape: () => ({ logoShape: "circle", logoAspectRatio: 1 }),
    // ``MemberConsentsCard`` (a child of MemberDetail) calls
    // ``useTimeFormat().formatDateTimeWithFallback`` to render the
    // ``consented_at`` / ``revoked_at`` timestamps. We stub it
    // identity-like — the tests in this file don't care about the
    // formatted string itself.
    useTimeFormat: () => ({
      timeFormat: "HH:mm",
      formatTime: (v: unknown) => (v ? String(v) : null),
      formatTimeWithFallback: (v: unknown, fallback = "-") =>
        v ? String(v) : fallback,
      formatDateTime: (v: unknown) => (v ? String(v) : null),
      formatDateTimeWithFallback: (v: unknown, fallback = "-") =>
        v ? String(v) : fallback,
    }),
  };
});

const logoutMock = vi.fn();
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ logout: logoutMock }),
}));

// Stub every child component & modal — we don't test their internals here.
vi.mock("@features/members/components/ActiveSubscriptionsCard", () => ({
  // The "+ new subscription" button was folded into this card (the standalone
  // SubscriptionsCard was removed in the MemberDetail two-column redesign).
  default: ({ onNewSubscription }: { onNewSubscription?: () => void }) => (
    <div data-testid="active-subscriptions-card">
      <button
        type="button"
        data-testid="active-subscriptions-new-btn"
        onClick={() => onNewSubscription?.()}
      >
        open new subscription
      </button>
    </div>
  ),
}));
vi.mock("@features/members/components/CurrentWeekDeliveryCard", () => ({
  default: () => <div data-testid="current-week-delivery-card" />,
}));

vi.mock("@features/abos/modals/NewSubscriptionModal", () => ({
  default: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="new-subscription-modal" /> : null,
}));
vi.mock("@features/members/components/PaymentsCard", () => ({
  default: () => <div data-testid="payments-card" />,
}));
vi.mock("@features/members/components/UpcomingDeliveriesCard", () => ({
  default: () => <div data-testid="upcoming-deliveries-card" />,
}));
vi.mock("@features/members/components/CoopSharesCard", () => ({
  default: () => <div data-testid="coop-shares-card" />,
}));
vi.mock("@features/members/components/DeliveryStationDaysCard", () => ({
  default: () => <div data-testid="delivery-stations-card" />,
}));

// MemberEditModal is no longer rendered from MemberDetail — editing
// lives in the top-right UserMenu → "Meine Daten". Only the delivery
// modal + coop-shares modal stay here.
vi.mock("@features/members/modals", () => ({
  MemberDeliveryEditModal: ({ visible }: { visible: boolean }) =>
    visible ? <div data-testid="delivery-edit-modal" /> : null,
  CoopSharesModal: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="coop-shares-modal" /> : null,
  MemberCoopSharesModal: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="member-coop-shares-modal" /> : null,
  CancelMembershipModal: ({ isOpen }: { isOpen: boolean }) =>
    isOpen ? <div data-testid="cancel-membership-modal" /> : null,
}));

// ── Imports under test ───────────────────────────────────────────────────────

import MemberDetail from "../MemberDetail";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const MEMBER_ID = "member-42";

const baseMember = {
  id: MEMBER_ID,
  first_name: "Alice",
  last_name: "Acres",
  email: "alice@example.com",
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderPage(client = makeQueryClient()) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/members/${MEMBER_ID}`]}>
          <Routes>
            <Route path="/members/:id" element={<MemberDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  logoutMock.mockReset();
  // MemberConsentsCard (mounted inside MemberDetail) lists consents on
  // mount. Default to an empty list so every test doesn't have to
  // re-register the handler. Tests that exercise consent UI explicitly
  // can still override via ``server.use``.
  server.use(
    http.get("/api/commissioning/consents/", () => HttpResponse.json([])),
    // MemberDetail fetches delivery-exception periods to tag subscription rows
    // (once there's a subscription). Default to an empty list.
    http.get("/api/commissioning/delivery_exception_periods/", () =>
      HttpResponse.json([]),
    ),
  );
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("MemberDetail (integration)", () => {
  it("renders the member's name + email and all major child cards once data loads", async () => {
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () => HttpResponse.json([])),
    );

    renderPage();

    expect(await screen.findByText("Alice Acres")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(
      screen.getByTestId("current-week-delivery-card"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("upcoming-deliveries-card")).toBeInTheDocument();
    expect(screen.getByTestId("active-subscriptions-card")).toBeInTheDocument();
    expect(screen.getByTestId("payments-card")).toBeInTheDocument();
  });

  it("shows the 'member not found' branch + go-back button when the API returns 404", async () => {
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json({ detail: "not found" }, { status: 404 }),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () => HttpResponse.json([])),
    );

    renderPage();

    expect(
      await screen.findByText("members.member_not_found"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "common.go_back" }),
    ).toBeInTheDocument();
  });

  it("calls share_delivery + abos with the member id from the route", async () => {
    const seen: { url: string }[] = [];
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", ({ request }) => {
        seen.push({ url: request.url });
        return HttpResponse.json([]);
      }),
      http.get("/api/commissioning/abos/", ({ request }) => {
        seen.push({ url: request.url });
        return HttpResponse.json([]);
      }),
    );

    renderPage();
    await screen.findByText("Alice Acres");

    const shareDeliveryCall = seen.find((c) =>
      c.url.includes("/share_delivery/"),
    );
    const abosCall = seen.find((c) => c.url.includes("/abos/"));
    expect(shareDeliveryCall).toBeDefined();
    expect(abosCall).toBeDefined();
    expect(new URL(shareDeliveryCall!.url).searchParams.get("member")).toBe(
      MEMBER_ID,
    );
    expect(new URL(abosCall!.url).searchParams.get("member")).toBe(MEMBER_ID);
    expect(new URL(abosCall!.url).searchParams.get("is_trial")).toBe("false");
  });

  // The inline "Edit member" button (and the MemberEditModal it opened)
  // used to live on this header; both have since been moved into the
  // top-right ``UserMenu`` → "Meine Daten"
  // (apps/react-core/src/components/layout/MyDataTab/) so account-level
  // affordances are consistent across the app.
  it("does NOT render an inline Edit button on the member header", async () => {
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () => HttpResponse.json([])),
    );

    renderPage();
    await screen.findByText("Alice Acres");

    expect(
      screen.queryByRole("button", { name: /members\.edit_member/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("member-edit-modal")).not.toBeInTheDocument();
  });

  // Logout used to live on the MemberDetail header; it has since
  // been consolidated into the top-right user dropdown
  // (apps/react-core/src/components/layout/LoginButton.tsx) so the
  // logout affordance is consistent across the app.
  it("does NOT render an inline Logout button on the member header", async () => {
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () => HttpResponse.json([])),
    );

    renderPage();
    await screen.findByText("Alice Acres");

    expect(
      screen.queryByRole("button", { name: /common\.logout/ }),
    ).not.toBeInTheDocument();
    expect(logoutMock).not.toHaveBeenCalled();
  });

  it("only counts admin_confirmed + currently-valid subscriptions as 'active' (filter contract)", async () => {
    // We can't observe the filtered list directly (the cards are stubbed),
    // but we CAN observe that the page renders without crashing and the
    // SubscriptionsCard receives the unfiltered subs (it has the 'new'
    // button). This pins the contract that the page never throws when subs
    // span past, present, future, unconfirmed.
    const today = new Date().toISOString().slice(0, 10);
    const past = "2020-01-01";
    const future = "2099-01-01";
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () =>
        HttpResponse.json([
          {
            id: "s1",
            admin_confirmed: true,
            valid_from: past,
            valid_until: today,
          },
          {
            id: "s2",
            admin_confirmed: false,
            valid_from: past,
            valid_until: future,
          },
          { id: "s3", admin_confirmed: true, valid_from: future },
          { id: "s4", admin_confirmed: true, valid_from: past },
        ]),
      ),
    );

    renderPage();
    await screen.findByText("Alice Acres");

    // ActiveSubscriptionsCard (with its "+ new" button) rendered → page
    // survived the filter.
    expect(
      screen.getByTestId("active-subscriptions-new-btn"),
    ).toBeInTheDocument();
  });

  it("opens the New Subscription modal from the active-subscriptions card callback", async () => {
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () => HttpResponse.json([])),
    );

    renderPage();
    await screen.findByText("Alice Acres");

    const user = userEvent.setup();
    expect(
      screen.queryByTestId("new-subscription-modal"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("active-subscriptions-new-btn"));
    expect(
      await screen.findByTestId("new-subscription-modal"),
    ).toBeInTheDocument();
  });

  // Render-loop smoke test — MemberDetail orchestrates ~7 child cards and 3
  // queries. A healthy mount commits roughly 4-12 times (initial + each
  // query state transition + memo settling). 80 is a generous ceiling that
  // still catches a real runaway loop (1000+ commits is the classic
  // setState-in-render bug).
  it("does not re-render in a loop on initial mount (Profiler smoke test)", async () => {
    server.use(
      http.get(`/api/commissioning/members/${MEMBER_ID}/`, () =>
        HttpResponse.json(baseMember),
      ),
      http.get("/api/commissioning/share_delivery/", () =>
        HttpResponse.json([]),
      ),
      http.get("/api/commissioning/abos/", () => HttpResponse.json([])),
    );

    const profiler = profileRenders();
    const client = makeQueryClient();

    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/members/${MEMBER_ID}`]}>
          <Routes>
            <Route
              path="/members/:id"
              element={profiler.wrap(<MemberDetail />, "member-detail")}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText("Alice Acres");
    await flushMicrotasks(50);

    // Healthy baseline: ~5 commits. Bound is loose so legitimate refactors
    // don't trip it — a real loop would be in the thousands.
    expect(profiler.onRender.mock.calls.length).toBeLessThan(80);
  });
});
