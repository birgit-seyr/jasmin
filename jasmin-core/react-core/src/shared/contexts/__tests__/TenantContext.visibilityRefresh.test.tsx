/**
 * ``TenantProvider`` re-reads the full tenant when the tab becomes visible
 * again, so a setting changed by another office user or in another tab (e.g.
 * ``onboarding_mode``) reaches ``getSetting`` without a reload. A refresh that
 * finds the same payload keeps the state object, so no consumer re-renders.
 *
 * Boundary mocked: the generated tenants API. The real tokenStore decides
 * whether the user is logged in.
 */
import React, { useContext } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  currentRetrieve: vi.fn(),
  tenantsRetrieve: vi.fn(),
}));

vi.mock("@shared/api/generated/tenants/tenants", () => ({
  tenantsCurrentRetrieve: (...args: unknown[]) => api.currentRetrieve(...args),
  tenantsTenantsRetrieve: (...args: unknown[]) => api.tenantsRetrieve(...args),
}));

import { TenantContext, TenantProvider } from "../TenantContext";
import {
  clearAccessToken,
  setAccessToken,
} from "@shared/services/tokenStore";

const visibility = { state: "visible" as DocumentVisibilityState };
let renderCount = 0;

function Probe() {
  const context = useContext(TenantContext);
  renderCount += 1;
  return (
    <span data-testid="onboarding-mode">
      {String(context?.getSetting("onboarding_mode", "unset"))}
    </span>
  );
}

function fullTenant(onboardingMode: boolean) {
  return {
    id: "tenant-1",
    name: "Solawi",
    settings: { onboarding_mode: onboardingMode },
  };
}

function becomeVisibleAgain() {
  visibility.state = "hidden";
  document.dispatchEvent(new Event("visibilitychange"));
  visibility.state = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
}

async function renderLoadedProvider() {
  render(
    <TenantProvider>
      <Probe />
    </TenantProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("onboarding-mode")).toHaveTextContent("false"),
  );
  expect(api.tenantsRetrieve).toHaveBeenCalledTimes(1);
}

beforeEach(() => {
  renderCount = 0;
  visibility.state = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility.state,
  });
  api.currentRetrieve.mockReset().mockResolvedValue({
    id: "tenant-1",
    name: "Solawi",
  });
  api.tenantsRetrieve.mockReset().mockResolvedValue(fullTenant(false));
  setAccessToken("access-token");
});

afterEach(() => {
  clearAccessToken();
});

describe("TenantProvider refresh when the tab becomes visible", () => {
  it("picks up a setting changed elsewhere", async () => {
    await renderLoadedProvider();
    api.tenantsRetrieve.mockResolvedValue(fullTenant(true));

    act(() => becomeVisibleAgain());

    await waitFor(() =>
      expect(screen.getByTestId("onboarding-mode")).toHaveTextContent("true"),
    );
    expect(api.tenantsRetrieve).toHaveBeenCalledTimes(2);
  });

  it("does not fetch while the tab is hidden", async () => {
    await renderLoadedProvider();

    act(() => {
      visibility.state = "hidden";
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(api.tenantsRetrieve).toHaveBeenCalledTimes(1);
  });

  it("does not fetch after logout", async () => {
    await renderLoadedProvider();
    clearAccessToken();

    act(() => becomeVisibleAgain());

    expect(api.tenantsRetrieve).toHaveBeenCalledTimes(1);
  });

  it("re-renders no consumer when the payload is unchanged", async () => {
    await renderLoadedProvider();
    const rendersBefore = renderCount;

    await act(async () => becomeVisibleAgain());
    await waitFor(() => expect(api.tenantsRetrieve).toHaveBeenCalledTimes(2));
    await act(async () => {});

    expect(renderCount).toBe(rendersBefore);
    expect(screen.getByTestId("onboarding-mode")).toHaveTextContent("false");
  });
});
