import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { Suspense, lazy } from "react";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "@shared/contexts/AuthContext";
import { LocaleProvider } from "@shared/contexts/LocalContext";
import { TenantProvider, isPlatformDomain } from "@shared/contexts/TenantContext";
import ErrorBoundary from "@shared/ui/ErrorBoundary";
import { StepUpProvider } from "@shared/auth/StepUpProvider";
import { LiveAnnouncer, OfflineBanner } from "@shared/ui";
const SuperAdminApp = lazy(() => import("./SuperAdminApp"));
const JasminApp = lazy(() => import("./JasminApp"));
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

// Global error fallbacks for React Query. Any useQuery/useMutation that
// doesn't handle its own error path will surface a toast with a sensible
// message. Callers that already render their own error UI (e.g. the auth
// pages, the EditableTable banner) opt out per-call with
// `meta: { silent: true }`.
const shouldSurfaceError = (
  err: unknown,
  meta: Record<string, unknown> | undefined,
): boolean => {
  if (meta?.silent) return false;
  // 401 is handled by the axios interceptor's silent-refresh flow; the
  // user is either getting transparently re-authed or being redirected to
  // /login — a toast on top would be noise.
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status === 401) return false;
  return true;
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Always refetch on mount: this is an internal staff tool where data
      // freshness matters more than saving the occasional network round-trip,
      // and per-mutation invalidation isn't always exhaustive across pages.
      // Cached data still paints instantly while the background refetch runs.
      staleTime: 0,
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => {
        if (
          (error as { response?: { status?: number } })?.response?.status ===
          401
        )
          return false;
        return failureCount < 3;
      },
    },
  },
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (!shouldSurfaceError(error, query.meta)) return;
      notify.error(getErrorMessage(error, "Failed to load data"));
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (!shouldSurfaceError(error, mutation.meta)) return;
      notify.error(getErrorMessage(error, "Action failed"));
    },
  }),
});

function App() {
  const isPlatform = isPlatformDomain();

  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <OfflineBanner />
        <LiveAnnouncer />
        {isPlatform ? (
          // Platform domain - no TenantProvider needed
          <ErrorBoundary context="super admin">
            <AuthProvider>
              <LocaleProvider>
                <StepUpProvider>
                  <Suspense
                    fallback={<div className="page-loading">Loading…</div>}
                  >
                    <SuperAdminApp />
                  </Suspense>
                  {process.env.NODE_ENV === "development" && (
                    <ReactQueryDevtools initialIsOpen={false} />
                  )}
                </StepUpProvider>
              </LocaleProvider>
            </AuthProvider>
          </ErrorBoundary>
        ) : (
          // Tenant domain - with TenantProvider
          <ErrorBoundary>
            <TenantProvider>
              <AuthProvider>
                <LocaleProvider>
                  <StepUpProvider>
                    <Suspense
                      fallback={
                        <div
                          className="page-loading"
                          role="status"
                          aria-live="polite"
                        >
                          Loading…
                        </div>
                      }
                    >
                      <JasminApp />
                    </Suspense>
                    {process.env.NODE_ENV === "development" && (
                      <ReactQueryDevtools initialIsOpen={false} />
                    )}
                  </StepUpProvider>
                </LocaleProvider>
              </AuthProvider>
            </TenantProvider>
          </ErrorBoundary>
        )}
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
