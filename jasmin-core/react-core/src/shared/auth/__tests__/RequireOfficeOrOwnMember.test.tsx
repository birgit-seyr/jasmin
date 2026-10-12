/**
 * The member page opens for the office on every member and for a member on
 * their own record — whatever staff roles they also hold — where the page
 * shows the member's self-service view (``useMemberSelfService``).
 */
import { render, renderHook, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewer = vi.hoisted(() => ({
  isOffice: false,
  memberId: "member-7" as string | null,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@shared/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "user-1", member_id: viewer.memberId } }),
}));

vi.mock("../useRoles", () => ({
  useRoles: () => ({ isOffice: viewer.isOffice }),
}));

import { RequireOfficeOrOwnMember } from "../RequireOfficeOrOwnMember";
import { useMemberSelfService } from "../useMemberSelfService";

beforeEach(() => {
  viewer.isOffice = false;
  viewer.memberId = "member-7";
});

describe("useMemberSelfService", () => {
  it("is the member's own view on their own record", () => {
    const { result } = renderHook(() => useMemberSelfService("member-7"));

    expect(result.current).toBe(true);
  });

  it("gives office users the office view on their own record", () => {
    viewer.isOffice = true;
    const { result } = renderHook(() => useMemberSelfService("member-7"));

    expect(result.current).toBe(false);
  });

  it("is no self-service on another member's record", () => {
    const { result } = renderHook(() => useMemberSelfService("member-8"));

    expect(result.current).toBe(false);
  });

  it("is no self-service for a viewer without a member record", () => {
    viewer.memberId = null;
    const { result } = renderHook(() => useMemberSelfService("member-7"));

    expect(result.current).toBe(false);
  });
});

describe("RequireOfficeOrOwnMember", () => {
  const renderPage = (memberId: string) =>
    render(
      <MemoryRouter initialEntries={[`/members/members/${memberId}`]}>
        <Routes>
          <Route
            path="/members/members/:id"
            element={
              <RequireOfficeOrOwnMember>
                <p>member page</p>
              </RequireOfficeOrOwnMember>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

  it("opens a member's own page", () => {
    renderPage("member-7");

    expect(screen.getByText("member page")).toBeInTheDocument();
  });

  it("opens every member's page for the office", () => {
    viewer.isOffice = true;
    renderPage("member-8");

    expect(screen.getByText("member page")).toBeInTheDocument();
  });

  it("refuses another member's page", () => {
    renderPage("member-8");

    expect(screen.queryByText("member page")).not.toBeInTheDocument();
    expect(screen.getByText("auth.not_authorized.title")).toBeInTheDocument();
  });
});
