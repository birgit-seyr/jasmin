import {
  QueryCache,
  QueryClient,
  QueryClientProvider,
  useQuery,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

vi.mock("@shared/selectors", () => ({ YearSelector: () => null }));
vi.mock("@features/abos/modals/CreateBillingRunModal", () => ({
  CreateBillingRunModal: () => null,
}));

const { notifyMock, listRuns } = vi.hoisted(() => ({
  notifyMock: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  listRuns: vi.fn(),
}));

vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  notify: notifyMock,
}));

// The list hook runs a real query with the page's own options, so the meta
// the page passes reaches the query cache.
vi.mock(
  "@shared/api/generated/payments-—-billing-runs/payments-—-billing-runs",
  () => ({
    getPaymentsBillingRunsListQueryKey: (params?: unknown) => [
      "billing-runs",
      ...(params ? [params] : []),
    ],
    paymentsBillingRunsDestroy: vi.fn(),
    paymentsBillingRunsExportCreate: vi.fn(),
    usePaymentsBillingRunsList: (
      params: unknown,
      options?: { query?: Partial<UseQueryOptions> },
    ) =>
      useQuery({
        ...options?.query,
        queryKey: ["billing-runs", params],
        queryFn: () => listRuns(params),
      }),
  }),
);

import DebitsAbos from "../DebitsAbos";

describe("DebitsAbos", () => {
  it("reports a failed load once, in its own words", async () => {
    listRuns.mockRejectedValue({ isAxiosError: true, response: { status: 503, data: {} } });
    // The app's toast for a failed query, unless it sets `meta: { silent: true }`.
    const appToast = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
      queryCache: new QueryCache({
        onError: (error, query) => {
          if (!query.meta?.silent) appToast(error);
        },
      }),
    });

    render(
      <QueryClientProvider client={queryClient}>
        <DebitsAbos />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(notifyMock.error).toHaveBeenCalledWith("abos.debits_load_error"),
    );
    expect(notifyMock.error).toHaveBeenCalledTimes(1);
    expect(appToast).not.toHaveBeenCalled();
  });
});
