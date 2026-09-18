import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { makeUseTenantMock } from "@/test/tenantMock";

// ``vi.mock`` factories are hoisted above the imports, so anything a factory
// reads has to exist before module evaluation.
const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  // Reassigned by ``renderPage`` before each mount, read lazily inside the
  // ``useTenant`` stub.
  useTenantValue: null as unknown,
}));

// The page reads ``useTenant()``; the fallback template additionally formats
// its "last updated" date through ``useDateFormat()``. Identity formatter so
// the page suite never depends on a date format.
vi.mock("@hooks/index", () => ({
  useTenant: () => mocks.useTenantValue,
  useDateFormat: () => ({ formatDate: (value: unknown) => String(value) }),
}));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import PrivacyPolicyPage from "../PrivacyPolicyPage";

// Only ``DefaultPrivacyPolicyTemplate`` emits this heading, so its presence
// (or absence) is the tell for which of the two branches rendered.
const TEMPLATE_ONLY_HEADING = "privacy.controller_title";

function renderPage(tenant: unknown) {
  mocks.useTenantValue = makeUseTenantMock({ tenant });
  return render(
    <MemoryRouter>
      <PrivacyPolicyPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.navigate.mockReset();
});

describe("PrivacyPolicyPage", () => {
  it("renders the tenant's own policy HTML and suppresses the default template", () => {
    renderPage({
      name: "Sunfield Farm Cooperative",
      privacy_policy_html:
        "<h2>Sunfield privacy statement</h2><p>We store member data on our own server.</p>",
    });

    expect(
      screen.getByRole("heading", { name: "Sunfield privacy statement" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("We store member data on our own server."),
    ).toBeInTheDocument();

    expect(screen.queryByText(TEMPLATE_ONLY_HEADING)).not.toBeInTheDocument();
    expect(screen.queryByText(/privacy\.last_updated/)).not.toBeInTheDocument();
  });

  it("falls back to the default template when the override is whitespace only", () => {
    // The page trims before deciding. Without that trim a blank override is
    // truthy and the visitor gets an empty privacy page — the branch most
    // likely to regress.
    renderPage({
      name: "Sunfield Farm Cooperative",
      privacy_policy_html: "   \n\t  ",
    });

    expect(screen.getByText(TEMPLATE_ONLY_HEADING)).toBeInTheDocument();
    expect(screen.getByText("Sunfield Farm Cooperative")).toBeInTheDocument();
  });

  it.each([
    ["a null tenant", null],
    ["an undefined tenant", undefined],
    ["a tenant row that carries no override field", { name: "Sunfield Farm" }],
    [
      "an empty-string override",
      { name: "Sunfield Farm", privacy_policy_html: "" },
    ],
  ])("falls back to the default template for %s", (_label, tenant) => {
    renderPage(tenant);

    expect(screen.getByText(TEMPLATE_ONLY_HEADING)).toBeInTheDocument();
  });

  it("strips scripts and inline event handlers out of the tenant override", () => {
    const { container } = renderPage({
      privacy_policy_html:
        "<p>Contact our data protection officer.</p>" +
        "<script>window.__privacyPolicyXss = true;</script>" +
        '<img src="x" alt="certification seal" onerror="window.__privacyPolicyXss = true">',
    });

    // The benign markup around the payload still reaches the visitor.
    expect(
      screen.getByText("Contact our data protection officer."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "certification seal" }),
    ).toBeInTheDocument();

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")?.getAttribute("onerror")).toBeNull();
    expect(container.innerHTML).not.toContain("__privacyPolicyXss");
  });

  it("sends the visitor back through history when the back button is pressed", async () => {
    renderPage(null);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /common\.back/ }));

    expect(mocks.navigate).toHaveBeenCalledTimes(1);
    expect(mocks.navigate).toHaveBeenCalledWith(-1);
  });
});
