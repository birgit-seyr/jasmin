/**
 * StepUpProvider + runStepUpFlow integration (A22 regression).
 *
 * The contract under test: the modal verifies the password BEFORE
 * resolving the prompt promise. A wrong password shows the backend
 * error inside the modal and lets the user retry — it must NOT reject
 * the in-flight ``runStepUpFlow`` (which would fail the user's
 * original destructive action). Cancelling rejects the flow.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { runStepUpFlow } from "@shared/services/stepUp";
import { getAccessToken, setAccessToken } from "@shared/services/tokenStore";
import StepUpProvider from "../StepUpProvider";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const axiosPostMock = vi.hoisted(() => vi.fn());
vi.mock("axios", () => ({
  default: { post: axiosPostMock },
}));

function wrongPasswordError() {
  return {
    isAxiosError: true,
    response: {
      status: 400,
      // Deliberately NOT a code from errors.json — ``getErrorMessage``
      // would otherwise return the catalogue translation instead of
      // the backend message we assert on.
      data: { code: "auth.step_up_test_code", message: "Invalid password." },
    },
  };
}

async function submitPassword(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("auth.step_up.password"), "hunter2");
  await user.click(screen.getByRole("button", { name: "auth.step_up.submit" }));
}

describe("StepUpProvider", () => {
  beforeEach(() => {
    axiosPostMock.mockReset();
    setAccessToken("stale-token");
  });

  it("wrong password keeps the modal open with the error and allows a retry", async () => {
    const user = userEvent.setup();
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );

    const flow = runStepUpFlow({ ttlSeconds: 300 });
    // Guard against an unhandled-rejection blowup if an assertion
    // below fails before we await the flow.
    flow.catch(() => {});

    await screen.findByText("auth.step_up.title");

    // Attempt 1 — backend rejects the password.
    axiosPostMock.mockRejectedValueOnce(wrongPasswordError());
    await submitPassword(user);

    // The error surfaces INSIDE the modal; the flow stays pending and
    // the stale token is untouched.
    await screen.findByText("Invalid password.");
    expect(screen.getByText("auth.step_up.title")).toBeInTheDocument();
    expect(getAccessToken()).toBe("stale-token");

    // Attempt 2 — correct password.
    axiosPostMock.mockResolvedValueOnce({
      data: { access: "sudo-token", ttl_seconds: 300 },
    });
    await submitPassword(user);

    await expect(flow).resolves.toBe("sudo-token");
    expect(getAccessToken()).toBe("sudo-token");
    await waitFor(() =>
      expect(screen.queryByLabelText("auth.step_up.password")).not.toBeInTheDocument(),
    );
  });

  it("unmounting mid-prompt rejects the flow so a later flow can start", async () => {
    const { unmount } = render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );

    const flow = runStepUpFlow({ ttlSeconds: 300 });
    flow.catch(() => {});
    await screen.findByText("auth.step_up.title");

    // e.g. an ErrorBoundary swapping the tree for its fallback. The
    // pending promise must settle here — otherwise ``runStepUpFlow``'s
    // ``inFlight`` dedup stays wedged and every later destructive
    // request hangs until a full page reload.
    unmount();
    await expect(flow).rejects.toThrow("StepUpProvider unmounted");

    // A remounted provider (ErrorBoundary "Try again") serves a fresh
    // flow instead of returning the dead in-flight promise.
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );
    const secondFlow = runStepUpFlow({ ttlSeconds: 300 });
    secondFlow.catch(() => {});
    await screen.findByText("auth.step_up.title");
    axiosPostMock.mockResolvedValueOnce({
      data: { access: "sudo-token-2", ttl_seconds: 300 },
    });
    await submitPassword(userEvent.setup());
    await expect(secondFlow).resolves.toBe("sudo-token-2");
  });

  it("cancelling the modal rejects the flow", async () => {
    const user = userEvent.setup();
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );

    const flow = runStepUpFlow({ ttlSeconds: 300 });
    flow.catch(() => {});
    await screen.findByText("auth.step_up.title");

    await user.click(screen.getByRole("button", { name: "common.cancel" }));

    await expect(flow).rejects.toThrow("step-up cancelled by user");
    expect(axiosPostMock).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe("stale-token");
  });
});
