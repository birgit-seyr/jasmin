import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { server } from "@/test/msw/server";
import Step5Consents from "../steps/Step5Consents";
import type { RegistrationData } from "../types";

// ``Trans`` + ``initReactI18next`` are exported even though we don't
// use them — ``src/i18n/index.ts`` is pulled in transitively (via
// ConsentBlock → useTenant → apiError) and calls ``.use(initReactI18next)``
// at module load; without these the test file fails to import.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// Step5Consents renders three ConsentBlocks; ConsentBlock calls
// ``useTenant().getSetting("date_format")``. Stub the hook here so
// the test doesn't need a real TenantProvider — same pattern as
// LoginPage.test.tsx and the ConsentBlock unit test.
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock({
    tenant: { tenant_language: "de" },
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "date_format" ? "DD/MM/YYYY" : defaultValue,
  });
  return {
    useTenant: () => tenant,
    useDateFormat: () => ({ dateFormat: "DD/MM/YYYY", mobileDateFormat: "DD/MM" }),
  };
});

// The three documents Step5Consents fetches. Each /current/ request
// looks up the kind from the ``?kind=`` query param.
const DOCS_BY_KIND: Record<string, Record<string, unknown>> = {
  privacy: {
    id: "doc-privacy",
    kind: "privacy",
    version: "1",
    locale: "de",
    title: "Privacy",
    body: "Privacy body",
    body_sha256: "p1",
    valid_from: "2026-01-01",
    created_at: "2026-01-01T00:00:00Z",
  },
  withdrawal: {
    id: "doc-withdrawal",
    kind: "withdrawal",
    version: "1",
    locale: "de",
    title: "Withdrawal",
    body: "Withdrawal body",
    body_sha256: "w1",
    valid_from: "2026-01-01",
    created_at: "2026-01-01T00:00:00Z",
  },
  terms: {
    id: "doc-terms",
    kind: "terms",
    version: "1",
    locale: "de",
    title: "Terms",
    body: "Terms body",
    body_sha256: "t1",
    valid_from: "2026-01-01",
    created_at: "2026-01-01T00:00:00Z",
  },
};

function installDocHandlers() {
  server.use(
    http.get(
      "/api/commissioning/consent_documents/current/",
      ({ request }) => {
        const kind = new URL(request.url).searchParams.get("kind") ?? "";
        const doc = DOCS_BY_KIND[kind];
        if (!doc) {
          return HttpResponse.json({ detail: "not found" }, { status: 404 });
        }
        return HttpResponse.json(doc);
      },
    ),
  );
}

function renderStep(initial: Partial<RegistrationData> = {}) {
  const updateMock = vi.fn();
  const nextMock = vi.fn();
  const backMock = vi.fn();

  let currentData: RegistrationData = { ...initial };
  const update = (partial: Partial<RegistrationData>) => {
    currentData = { ...currentData, ...partial };
    updateMock(partial);
  };

  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  const result = render(
    <QueryClientProvider client={client}>
      <Step5Consents
        data={currentData}
        update={update}
        next={nextMock}
        back={backMock}
      />
    </QueryClientProvider>,
  );

  return {
    updateMock,
    nextMock,
    backMock,
    rerenderWith: (data: RegistrationData) => {
      currentData = data;
      result.rerender(
        <QueryClientProvider client={client}>
          <Step5Consents
            data={data}
            update={update}
            next={nextMock}
            back={backMock}
          />
        </QueryClientProvider>,
      );
    },
    ...result,
  };
}

describe("Step5Consents", () => {
  it("renders one consent block per required kind once docs load", async () => {
    installDocHandlers();
    renderStep();

    expect(await screen.findByText("Privacy body")).toBeInTheDocument();
    expect(await screen.findByText("Withdrawal body")).toBeInTheDocument();
    expect(await screen.findByText("Terms body")).toBeInTheDocument();
  });

  it("keeps Next disabled until every required document is accepted", async () => {
    installDocHandlers();
    const { rerenderWith } = renderStep();

    const nextBtn = await screen.findByRole("button", {
      name: /auth\.registration\.actions\.next|next/i,
    });
    expect(nextBtn).toBeDisabled();

    // Simulate progressive acceptance via re-renders with mutated data
    // (the real parent stores into RegistrationData via update()).
    rerenderWith({
      accepted_consent_documents: { privacy: "doc-privacy" },
    });
    expect(nextBtn).toBeDisabled();

    rerenderWith({
      accepted_consent_documents: {
        privacy: "doc-privacy",
        withdrawal: "doc-withdrawal",
      },
    });
    expect(nextBtn).toBeDisabled();

    rerenderWith({
      accepted_consent_documents: {
        privacy: "doc-privacy",
        withdrawal: "doc-withdrawal",
        terms: "doc-terms",
      },
    });
    expect(nextBtn).not.toBeDisabled();
  });

  it("forwards (kind → document_id) into update() when a checkbox is ticked", async () => {
    installDocHandlers();
    const { updateMock } = renderStep();

    // ``findAllByRole`` resolves on the FIRST match (default min=1), so
    // we need to wait until all three blocks have finished loading
    // their documents — otherwise the click races the second/third
    // block's mount.
    await waitFor(() => {
      expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    });
    const checkboxes = screen.getAllByRole("checkbox");

    await userEvent.click(checkboxes[0]);

    // The first update() call may come from ConsentBlock's effect that
    // syncs the document_id back to the parent with checked=false.
    // The user click should produce an update with a non-empty
    // accepted_consent_documents.
    await waitFor(() => {
      const tickCall = updateMock.mock.calls.find(
        (call) =>
          call[0]?.accepted_consent_documents &&
          Object.keys(call[0].accepted_consent_documents).length > 0,
      );
      expect(tickCall).toBeDefined();
    });
  });
});
