import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Mock the two hooks ProtectedRoute consumes BEFORE importing it.
const useAuthMock = vi.fn();
const useTenantMock = vi.fn();

vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));
vi.mock("@hooks/index", () => ({
  useTenant: () => useTenantMock(),
}));
// UnauthorizedPage is rendered for the requiredSetting branch; stub it so
// the test doesn't pull a whole page tree.
vi.mock("@app/UnauthorizedPage", () => ({
  default: ({ message }: { message?: string }) => (
    <div data-testid="unauthorized-page">{message ?? "unauthorized"}</div>
  ),
}));

import { ProtectedRoute } from "../ProtectedRoute";

const PROTECTED = <div data-testid="protected">PROTECTED</div>;
const LOGIN = <div data-testid="login">LOGIN</div>;
const UNAUTH = <div data-testid="unauth-route">UNAUTH</div>;

function renderAt(path: string, meta?: Record<string, unknown>) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/private"
          element={<ProtectedRoute meta={meta}>{PROTECTED}</ProtectedRoute>}
        />
        <Route path="/login" element={LOGIN} />
        <Route path="/unauthorized" element={UNAUTH} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useAuthMock.mockReset();
  useTenantMock.mockReset();
  useTenantMock.mockReturnValue({ getSetting: () => true });
});

describe("ProtectedRoute", () => {
  it("renders a loading indicator while auth is initialising", () => {
    useAuthMock.mockReturnValue({
      loading: true,
      isAuthenticated: false,
      hasPermission: () => false,
      userRole: null,
      isSuperAdmin: false,
    });
    renderAt("/private");
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("redirects unauthenticated users to /login", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: false,
      hasPermission: () => false,
      userRole: null,
      isSuperAdmin: false,
    });
    renderAt("/private");
    expect(screen.getByTestId("login")).toBeInTheDocument();
  });

  it("super-admins bypass all checks", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => false, // would normally fail
      userRole: "office",
      isSuperAdmin: true,
    });
    renderAt("/private", { requiredRole: "admin" });
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("tenant superusers bypass meta checks", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => false,
      userRole: "superuser",
      isSuperAdmin: false,
    });
    renderAt("/private", { requiredRole: "office" });
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("redirects to /unauthorized when role does not match", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => true,
      userRole: "office",
      isSuperAdmin: false,
    });
    renderAt("/private", { requiredRole: "admin" });
    expect(screen.getByTestId("unauth-route")).toBeInTheDocument();
  });

  it("allows the route when the user holds an accepted role", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => false,
      userRole: "office",
      isSuperAdmin: false,
    });
    renderAt("/private", { requiredRole: ["office", "admin"] });
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("falls back to permission check for members (no role gate)", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: (p: string) => p === "view_thing",
      userRole: "member",
      isSuperAdmin: false,
    });
    renderAt("/private", { requiredPermission: "view_thing" });
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });

  it("redirects to /unauthorized when the required permission is missing", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => false,
      userRole: "member",
      isSuperAdmin: false,
    });
    renderAt("/private", { requiredPermission: "view_thing" });
    expect(screen.getByTestId("unauth-route")).toBeInTheDocument();
  });

  it("blocks the route with UnauthorizedPage when requiredSetting is disabled", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => true,
      userRole: "office",
      isSuperAdmin: false,
    });
    useTenantMock.mockReturnValue({
      getSetting: (key: string) => (key === "billing_enabled" ? false : true),
    });
    renderAt("/private", { requiredSetting: "billing_enabled" });
    expect(screen.getByTestId("unauthorized-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("allows the route when requiredSetting is enabled", () => {
    useAuthMock.mockReturnValue({
      loading: false,
      isAuthenticated: true,
      hasPermission: () => true,
      userRole: "office",
      isSuperAdmin: false,
    });
    useTenantMock.mockReturnValue({
      getSetting: () => true,
    });
    renderAt("/private", { requiredSetting: "billing_enabled" });
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });
});
