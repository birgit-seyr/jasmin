import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { server } from "../../../test/msw/server";
import ConsentBlock, { ConsentDocumentKind } from "../ConsentBlock";

// Full enum-value union ("privacy" | "sepa" | "withdrawal" | "terms"),
// not the literal type of any single member — so the helper accepts
// every kind the component does.
type ConsentKindValue =
  (typeof ConsentDocumentKind)[keyof typeof ConsentDocumentKind];

// Pin react-i18next to identity so assertions can match the keys/fallbacks
// directly without depending on the real i18n initialisation.
//
// ``Trans`` + ``initReactI18next`` are exported here even though the
// component doesn't read them — ``src/i18n/index.ts`` is pulled in
// transitively (utils/apiError → hooks/useTenant chain) and calls
// ``.use(initReactI18next)`` at module load. Without these the mock
// load fails before any test runs.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// ConsentBlock reads ``useTenant().getSetting("date_format")`` to
// format ``valid_from`` for display. We don't wrap the test in a
// ``<TenantProvider>`` because the component's behaviour we're
// asserting (fetch doc → render body → checkbox) doesn't depend on
// the real tenant context — a stub is enough.
vi.mock("@hooks/index", async () => {
  const { makeUseTenantMock } = await import("../../../test/tenantMock");
  const tenant = makeUseTenantMock({
    tenant: { tenant_language: "de" },
    // Test asserts a German date format — override the passthrough
    // ``getSetting`` for that one key only.
    getSetting: (key: string, defaultValue?: unknown) =>
      key === "date_format" ? "DD/MM/YYYY" : defaultValue,
  });
  return {
    useTenant: () => tenant,
    useDateFormat: () => ({ dateFormat: "DD/MM/YYYY", mobileDateFormat: "DD/MM" }),
  };
});

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

function renderBlock(opts: {
  kind?: ConsentKindValue;
  locale?: string;
  checked?: boolean;
  onChange?: (checked: boolean, documentId: string | undefined) => void;
}) {
  const onChange = opts.onChange ?? vi.fn();
  return {
    onChange,
    ...render(
      <QueryClientProvider client={makeClient()}>
        <ConsentBlock
          kind={opts.kind ?? ConsentDocumentKind.privacy}
          locale={opts.locale ?? "de"}
          checked={opts.checked ?? false}
          onChange={onChange}
        />
      </QueryClientProvider>,
    ),
  };
}

const SAMPLE_DOC = {
  id: "doc-1",
  kind: "privacy",
  version: "2026-05-20",
  locale: "de",
  title: "Datenschutzerklärung",
  valid_from: "2026-05-20",
  body: "We process your data lawfully and minimally.",
  body_sha256: "abcdef",
  created_at: "2026-05-20T10:00:00Z",
};

describe("ConsentBlock", () => {
  it("renders the document body and the version label once loaded", async () => {
    server.use(
      http.get("/api/commissioning/consent_documents/current/", () =>
        HttpResponse.json(SAMPLE_DOC),
      ),
    );

    renderBlock({});

    expect(await screen.findByText(SAMPLE_DOC.body)).toBeInTheDocument();
    expect(screen.getByText(/2026-05-20/)).toBeInTheDocument();
    // Title is rendered in the Card title slot — present somewhere.
    expect(screen.getByText(SAMPLE_DOC.title)).toBeInTheDocument();
  });

  it("emits the documentId via onChange when the document finishes loading", async () => {
    server.use(
      http.get("/api/commissioning/consent_documents/current/", () =>
        HttpResponse.json(SAMPLE_DOC),
      ),
    );

    const { onChange } = renderBlock({ checked: false });

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    // Effect hands back ``checked`` AS-IS plus the document_id.
    expect(onChange).toHaveBeenCalledWith(false, SAMPLE_DOC.id);
  });

  it("toggles via the checkbox and forwards both checked + documentId", async () => {
    server.use(
      http.get("/api/commissioning/consent_documents/current/", () =>
        HttpResponse.json(SAMPLE_DOC),
      ),
    );

    const onChange = vi.fn();
    renderBlock({ onChange, checked: false });

    const checkbox = await screen.findByRole("checkbox");
    await userEvent.click(checkbox);

    // The most recent call captures the user's tick.
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(true, SAMPLE_DOC.id),
    );
  });

  it("renders the missing-document error when the backend returns 404", async () => {
    server.use(
      http.get("/api/commissioning/consent_documents/current/", () =>
        HttpResponse.json({ detail: "not found" }, { status: 404 }),
      ),
    );

    renderBlock({ kind: ConsentDocumentKind.sepa });

    // The t() mock returns the key verbatim (no inline fallbacks), so the
    // missing-document alert surfaces its title key.
    expect(
      await screen.findByText("consent.block.missing_document_title"),
    ).toBeInTheDocument();
  });

  it("requests the right (kind, locale) query params", async () => {
    let captured: { kind?: string; locale?: string } | null = null;
    server.use(
      http.get(
        "/api/commissioning/consent_documents/current/",
        ({ request }) => {
          const url = new URL(request.url);
          captured = {
            kind: url.searchParams.get("kind") ?? undefined,
            locale: url.searchParams.get("locale") ?? undefined,
          };
          return HttpResponse.json(SAMPLE_DOC);
        },
      ),
    );

    renderBlock({ kind: ConsentDocumentKind.withdrawal, locale: "en" });

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toEqual({ kind: "withdrawal", locale: "en" });
  });
});
