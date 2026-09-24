import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

// ProtectedRoute consumes exactly one hook. Mock it before importing.
const useAuthMock = vi.fn();
vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));

import { ProtectedRoute } from "../ProtectedRoute";

/** Renders the login target and echoes the location state it was sent. */
function LoginProbe() {
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string } } | null)?.from;
  return <div data-testid="login">{from?.pathname ?? "no-from"}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/private"
          element={
            <ProtectedRoute>
              <div data-testid="protected">PROTECTED</div>
            </ProtectedRoute>
          }
        />
        <Route path="/login" element={<LoginProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
});

describe("ProtectedRoute", () => {
  it("renders a loading indicator while auth is initialising", () => {
    useAuthMock.mockReturnValue({ loading: true, isAuthenticated: false });
    renderAt("/private");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("redirects unauthenticated users to /login", () => {
    useAuthMock.mockReturnValue({ loading: false, isAuthenticated: false });
    renderAt("/private");
    expect(screen.getByTestId("login")).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("carries the attempted path so login can send the user back", () => {
    useAuthMock.mockReturnValue({ loading: false, isAuthenticated: false });
    renderAt("/private");
    expect(screen.getByTestId("login")).toHaveTextContent("/private");
  });

  it("renders the route once authenticated", () => {
    useAuthMock.mockReturnValue({ loading: false, isAuthenticated: true });
    renderAt("/private");
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  // Authorization is RequireRole's job, inside the route files. ProtectedRoute
  // deliberately admits every authenticated user regardless of role — a role
  // check here would have to use the singular, order-dependent ``userRole``.
  it("does not gate on role", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      userRole: "member",
      isSuperAdmin: false,
    });
    renderAt("/private");
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });
});
