import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { server } from "@/test/msw/server";
import Step7Done from "../steps/Step7Done";
import type { RegistrationData } from "../types";

// FriendlyCaptcha (mounted on the form) calls useTenant(); hand it a static
// stub so the step renders without a real TenantProvider. Empty sitekey ->
// the widget renders null and the form submits frc_captcha_solution="".
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  // src/i18n/index.ts (pulled in transitively via utils/apiError) does
  // ``.use(initReactI18next)`` at module load — the mock has to expose it
  // even if our component never touches translations directly.
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

const SAMPLE_DATA: RegistrationData = {
  first_name: "Alice",
  last_name: "Schmidt",
  email: "alice@example.com",
  email_verified: true,
  coop_shares_count: 2,
  share_type_variation_id: "stv-1",
  quantity: 1,
  accepted_consent_documents: {
    privacy: "doc-privacy",
    withdrawal: "doc-withdrawal",
    terms: "doc-terms",
  },
  password: "L0ngEnoughPwd!Solid",
};

function renderStep(data: RegistrationData = SAMPLE_DATA) {
  const updateMock = vi.fn();
  const backMock = vi.fn();
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Step7Done
          data={data}
          update={updateMock}
          next={vi.fn()}
          back={backMock}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function clickSubmit() {
  // The submit button is the second action; the first is "Back".
  const submitBtn = screen
    .getAllByRole("button")
    .find((b) => /submit|absenden/i.test(b.textContent ?? ""));
  expect(submitBtn).toBeDefined();
  await userEvent.click(submitBtn!);
}

describe("Step7Done — submit flow", () => {
  it("POSTs the full payload to /api/auth/register/ and navigates to /login", async () => {
    let registerBody: Record<string, unknown> | null = null;

    server.use(
      http.post("/api/auth/register/", async ({ request }) => {
        registerBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            message: "ok",
            member_id: "member-42",
            coop_shares_created: 1,
            consent_records_created: 3,
          },
          { status: 201 },
        );
      }),
    );

    navigateMock.mockReset();
    renderStep();
    await clickSubmit();

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/login"));

    // Single atomic POST carries everything the wizard collected.
    expect(registerBody).toMatchObject({
      email: "alice@example.com",
      password: "L0ngEnoughPwd!Solid",
      first_name: "Alice",
      last_name: "Schmidt",
      coop_shares_count: 2,
      share_type_variation_id: "stv-1",
      quantity: 1,
      accepted_consent_documents: {
        privacy: "doc-privacy",
        withdrawal: "doc-withdrawal",
        terms: "doc-terms",
      },
    });
  });

  it("surfaces a register failure and does NOT navigate", async () => {
    server.use(
      http.post("/api/auth/register/", () =>
        HttpResponse.json(
          { detail: "Could not register with the provided details." },
          { status: 400 },
        ),
      ),
    );

    navigateMock.mockReset();
    renderStep();
    await clickSubmit();

    // Step7Done renders the error inside an antd ``<Alert>`` (role="alert").
    // Scoping to that role avoids matching the success Result text or any
    // of the Descriptions row labels that happen to contain "email".
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not register/i);
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
