/**
 * The super-admin dashboard: the tenant list with its counts, the note on
 * where the database backups live, and the create-tenant modal. Super-admin
 * endpoints have no generated client, so the shared axios instance is the
 * boundary mocked here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { api, notify, auth } = vi.hoisted(() => ({
  api: { get: vi.fn(), post: vi.fn() },
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  auth: {
    state: { loading: false, isAuthenticated: true, isSuperAdmin: true },
    logout: vi.fn(),
  },
}));
vi.mock("@shared/services/api", () => ({ default: api }));
vi.mock("@shared/utils", () => ({ notify }));
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ ...auth.state, logout: auth.logout }),
}));

import SuperAdminDashboard from "../SuperAdminDashboard";

const TENANTS_URL = "/api/super-admin/tenants/";

interface TenantFixture {
  id: number;
  schema_name: string;
  name: string;
  domain?: string;
  is_active?: boolean;
  created_on?: string;
  user_count?: number;
}

const NORTH: TenantFixture = {
  id: 7,
  schema_name: "farm_north",
  name: "North Farm",
  domain: "north.example.org",
  is_active: true,
  created_on: "2025-03-10T12:00:00Z",
  user_count: 42,
};

const SOUTH: TenantFixture = {
  id: 8,
  schema_name: "garden_south",
  name: "South Garden",
  domain: "south.example.org",
  is_active: false,
  created_on: "2025-06-01T12:00:00Z",
  user_count: 5,
};

// A tenant row that carries none of the optional fields.
const EAST: TenantFixture = { id: 9, schema_name: "farm_east", name: "East Farm" };

// What the mocked backend currently returns; a test changes it to simulate a
// server-side change that a refetch then picks up.
let backend: {
  tenants: TenantFixture[];
  tenantsError: unknown;
};

function serveGets(overrides: Record<string, () => Promise<unknown>> = {}) {
  api.get.mockImplementation((url: string) => {
    const override = overrides[url];
    if (override) return override();
    if (url === TENANTS_URL) {
      return backend.tenantsError
        ? Promise.reject(backend.tenantsError)
        : Promise.resolve({ data: backend.tenants });
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
}

function deferred<T = unknown>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function apiError(message: string, status = 400) {
  return {
    isAxiosError: true,
    response: { status, data: { code: "validation_error", message } },
  };
}

function getCalls(url: string): number {
  return api.get.mock.calls.filter(([calledUrl]) => calledUrl === url).length;
}

beforeEach(() => {
  auth.state = { loading: false, isAuthenticated: true, isSuperAdmin: true };
  auth.logout.mockReset().mockResolvedValue(undefined);
  backend = {
    tenants: [NORTH, SOUTH],
    tenantsError: null,
  };
  api.get.mockReset();
  serveGets();
  api.post.mockReset().mockResolvedValue({ data: {} });
  Object.values(notify).forEach((fn) => fn.mockReset());
});

function TenantPage() {
  const { id } = useParams();
  return <p data-testid="tenant-page">{id}</p>;
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<SuperAdminDashboard />} />
          <Route path="/login" element={<p data-testid="login-page" />} />
          <Route path="/tenants/:id" element={<TenantPage />} />
          <Route
            path="/ops-checklist"
            element={<p data-testid="ops-checklist-page" />}
          />
          <Route
            path="/support-tickets"
            element={<p data-testid="support-tickets-page" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function findTenantsSection() {
  return screen.findByRole("heading", { level: 2, name: "All Tenants" });
}

function statValue(label: string): string {
  return (
    screen.getByRole("heading", { level: 3, name: label }).nextElementSibling
      ?.textContent ?? ""
  );
}

/** A tenant row's cells keyed by their column header. */
function tenantCells(schemaName: string): Record<string, HTMLElement> {
  const row = screen.getByText(schemaName).closest("tr") as HTMLElement;
  const headers = within(row.closest("table") as HTMLElement)
    .getAllByRole("columnheader")
    .map((header) => header.textContent ?? "");
  const cells = within(row).getAllByRole("cell");
  return Object.fromEntries(
    headers.map((header, index) => [header, cells[index]]),
  );
}

function backupsSection(): HTMLElement {
  return screen
    .getByRole("heading", { level: 2, name: "platform.backups.title" })
    .closest(".sa-section") as HTMLElement;
}

describe("SuperAdminDashboard access", () => {
  it.each([
    [
      "signed out",
      { loading: false, isAuthenticated: false, isSuperAdmin: false },
    ],
    [
      "signed in without super-admin rights",
      { loading: false, isAuthenticated: true, isSuperAdmin: false },
    ],
  ])(
    "sends a visitor who is %s to the login page without loading anything",
    async (_who, state) => {
      auth.state = state;
      renderPage();

      expect(await screen.findByTestId("login-page")).toBeInTheDocument();
      expect(api.get).not.toHaveBeenCalled();
    },
  );

  it("waits for the session check before redirecting or loading", () => {
    auth.state = { loading: true, isAuthenticated: false, isSuperAdmin: false };
    renderPage();

    expect(screen.getByText("Loading tenants...")).toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe("SuperAdminDashboard tenants", () => {
  it("shows a loading text until the tenants arrive", async () => {
    const tenants = deferred();
    serveGets({ [TENANTS_URL]: () => tenants.promise });
    renderPage();

    expect(screen.getByText("Loading tenants...")).toBeInTheDocument();

    tenants.resolve({ data: backend.tenants });
    expect(await findTenantsSection()).toBeInTheDocument();
    expect(screen.queryByText("Loading tenants...")).not.toBeInTheDocument();
  });

  it("counts all tenants and the active ones, taking a tenant without a status as active", async () => {
    backend.tenants = [NORTH, SOUTH, EAST];
    renderPage();
    await findTenantsSection();

    expect(statValue("Total Tenants")).toBe("3");
    expect(statValue("Active Tenants")).toBe("2");
  });

  it("lists each tenant with its schema, name, domain, creation date and user count", async () => {
    renderPage();
    await findTenantsSection();

    const north = tenantCells("farm_north");
    expect(north.name).toHaveTextContent("North Farm");
    expect(north.domain).toHaveTextContent("north.example.org");
    expect(north.created).toHaveTextContent("10.3.2025");
    expect(north.users).toHaveTextContent("42");
  });

  it("shows an active and an inactive tenant with different status badges", async () => {
    renderPage();
    await findTenantsSection();

    expect(tenantCells("farm_north").status.firstElementChild).toHaveClass(
      "sa-badge",
      "sa-badge--active",
    );
    expect(tenantCells("garden_south").status.firstElementChild).toHaveClass(
      "sa-badge",
      "sa-badge--inactive",
    );
  });

  it("names each tenant's status in words, not by colour alone", async () => {
    renderPage();
    await findTenantsSection();

    expect(tenantCells("farm_north").status).toHaveTextContent("Active");
    expect(tenantCells("garden_south").status).toHaveTextContent("Inactive");
  });

  it("fills in a missing domain, creation date and user count", async () => {
    backend.tenants = [EAST];
    renderPage();
    await findTenantsSection();

    const east = tenantCells("farm_east");
    expect(east.status.firstElementChild).toHaveClass("sa-badge--active");
    expect(east.domain).toHaveTextContent("No domain");
    expect(east.created).toHaveTextContent("N/A");
    expect(east.duration).toHaveTextContent("N/A");
    expect(east.users).toHaveTextContent("0");
  });

  it("says so when there are no tenants yet", async () => {
    backend.tenants = [];
    renderPage();
    await findTenantsSection();

    expect(
      screen.getByText("No tenants yet. Create your first tenant to get started."),
    ).toBeInTheDocument();
    expect(statValue("Total Tenants")).toBe("0");
    expect(statValue("Active Tenants")).toBe("0");
  });

  it("opens a tenant's detail page", async () => {
    const user = userEvent.setup();
    renderPage();
    await findTenantsSection();

    await user.click(
      within(tenantCells("garden_south")[""]).getByRole("button", {
        name: "Details",
      }),
    );

    expect(screen.getByTestId("tenant-page")).toHaveTextContent("8");
  });
});

describe("SuperAdminDashboard load error", () => {
  it("shows the server's message in place of the tenant list", async () => {
    backend.tenantsError = apiError("Service unavailable", 503);
    renderPage();

    expect(await screen.findByText("Service unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("All Tenants")).not.toBeInTheDocument();
  });

  it("shows a generic message when the error carries none", async () => {
    backend.tenantsError = {};
    renderPage();

    expect(
      await screen.findByText("Failed to load tenants"),
    ).toBeInTheDocument();
    expect(screen.queryByText("All Tenants")).not.toBeInTheDocument();
  });

  it("loads the tenants again on retry", async () => {
    backend.tenantsError = apiError("Service unavailable", 503);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Service unavailable");

    backend.tenantsError = null;
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await findTenantsSection()).toBeInTheDocument();
    expect(screen.getByText("farm_north")).toBeInTheDocument();
    expect(getCalls(TENANTS_URL)).toBe(2);
  });

  it("logs out from the error screen", async () => {
    backend.tenantsError = apiError("Service unavailable", 503);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Service unavailable");

    await user.click(screen.getByRole("button", { name: "Logout" }));

    expect(auth.logout).toHaveBeenCalledTimes(1);
  });
});

describe("SuperAdminDashboard tenant age", () => {
  const NOW = new Date(2026, 9, 5, 12, 0);
  const DAY_MS = 24 * 60 * 60 * 1000;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    [0, "Today"],
    [1, "1 day"],
    [12, "12 days"],
    [29, "29 days"],
    [30, "1 month"],
    [200, "6 months"],
    [364, "12 months"],
    [365, "1 year"],
    [1100, "3 years"],
  ])("shows the age of a tenant created %i day(s) ago as '%s'", async (days, age) => {
    const createdOn = new Date(NOW.getTime() - days * DAY_MS);
    backend.tenants = [{ ...NORTH, created_on: createdOn.toISOString() }];
    renderPage();
    await findTenantsSection();

    expect(tenantCells("farm_north").duration).toHaveTextContent(age);
    expect(tenantCells("farm_north").created).toHaveTextContent(
      createdOn.toLocaleDateString("de-DE"),
    );
  });
});

describe("SuperAdminDashboard backups", () => {
  it("points to the backup service instead of listing or starting backups", async () => {
    renderPage();
    await findTenantsSection();

    const section = backupsSection();
    expect(
      within(section).getByText("platform.backups.note"),
    ).toBeInTheDocument();
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
    expect(within(section).queryByRole("table")).not.toBeInTheDocument();
    expect(
      api.get.mock.calls.every(([url]) => !String(url).includes("backups")),
    ).toBe(true);
  });
});

describe("SuperAdminDashboard tenant creation", () => {
  it("opens the create-tenant modal and closes it on cancel", async () => {
    const user = userEvent.setup();
    renderPage();
    await findTenantsSection();

    await user.click(screen.getByRole("button", { name: "+ Create Tenant" }));
    const dialog = screen.getByRole("dialog", { name: "Create New Tenant" });

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("creates a tenant, closes the modal and reloads the tenant list", async () => {
    const user = userEvent.setup();
    renderPage();
    await findTenantsSection();

    await user.click(screen.getByRole("button", { name: "+ Create Tenant" }));
    const dialog = screen.getByRole("dialog", { name: "Create New Tenant" });
    const field = (placeholder: string) =>
      within(dialog).getByPlaceholderText(placeholder);
    await user.type(field("e.g., solawi_berlin"), "farm-west");
    await user.type(field("e.g., Solawi Berlin"), "West Farm");
    await user.type(field("e.g., solawi.localhost"), "west.localhost");
    await user.type(field("First name"), "Wendy");
    await user.type(field("Last name"), "West");
    await user.type(field("admin@example.com"), "wendy@west.example.org");
    await user.type(field("Password"), "a-long-admin-password");
    backend.tenants = [
      NORTH,
      SOUTH,
      { id: 10, schema_name: "farm_west", name: "West Farm", is_active: true },
    ];
    await user.click(within(dialog).getByRole("button", { name: "Create Tenant" }));

    expect(api.post).toHaveBeenCalledWith(TENANTS_URL, {
      schema_name: "farm_west",
      name: "West Farm",
      domain: "west.localhost",
      tenant_language: "de",
      admin_email: "wendy@west.example.org",
      admin_password: "a-long-admin-password",
      admin_first_name: "Wendy",
      admin_last_name: "West",
    });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("farm_west")).toBeInTheDocument();
    expect(statValue("Total Tenants")).toBe("3");
    expect(getCalls(TENANTS_URL)).toBe(2);
  });
});

describe("SuperAdminDashboard header", () => {
  it.each([
    { button: "Ops Checklist", page: "ops-checklist-page" },
    { button: "Support Tickets", page: "support-tickets-page" },
  ])("opens the $button page", async ({ button, page }) => {
    const user = userEvent.setup();
    renderPage();
    await findTenantsSection();

    await user.click(screen.getByRole("button", { name: button }));

    expect(screen.getByTestId(page)).toBeInTheDocument();
  });

  it("logs out", async () => {
    const user = userEvent.setup();
    renderPage();
    await findTenantsSection();

    await user.click(screen.getByRole("button", { name: "Logout" }));

    expect(auth.logout).toHaveBeenCalledTimes(1);
  });
});
