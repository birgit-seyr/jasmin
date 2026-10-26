/**
 * StepUpProvider + runStepUpFlow integration.
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

import i18n from "@shared/i18n";
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

/** An access token whose ``exp`` lies ``seconds`` from now. */
function tokenEnding(seconds: number): string {
  const exp = Math.floor(Date.now() / 1000) + seconds;
  return `header.${btoa(JSON.stringify({ exp }))}.signature`;
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

  it("renews a session that would end inside the step-up window before asking", async () => {
    const user = userEvent.setup();
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );
    setAccessToken(tokenEnding(120));
    const refresh = vi.fn(async () => setAccessToken("fresh-token"));

    const flow = runStepUpFlow({ ttlSeconds: 300, refresh });
    flow.catch(() => {});
    await screen.findByText("auth.step_up.title");
    expect(refresh).toHaveBeenCalledTimes(1);

    axiosPostMock.mockResolvedValueOnce({
      data: { access: "sudo-token", ttl_seconds: 300 },
    });
    await submitPassword(user);

    await expect(flow).resolves.toBe("sudo-token");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(axiosPostMock.mock.calls[0][2].headers).toEqual({
      Authorization: "Bearer fresh-token",
    });
  });

  it("leaves a session that outlasts the step-up window as it is", async () => {
    const user = userEvent.setup();
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );
    const presented = tokenEnding(900);
    setAccessToken(presented);
    const refresh = vi.fn();

    const flow = runStepUpFlow({ ttlSeconds: 300, refresh });
    flow.catch(() => {});
    await screen.findByText("auth.step_up.title");
    axiosPostMock.mockResolvedValueOnce({
      data: { access: "sudo-token", ttl_seconds: 300 },
    });
    await submitPassword(user);

    await expect(flow).resolves.toBe("sudo-token");
    expect(refresh).not.toHaveBeenCalled();
    expect(axiosPostMock.mock.calls[0][2].headers).toEqual({
      Authorization: `Bearer ${presented}`,
    });
  });

  it("ends the flow without opening the modal when the renewal fails", async () => {
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );
    setAccessToken(tokenEnding(60));
    const refresh = vi.fn(() => Promise.reject(new Error("refresh refused")));

    await expect(runStepUpFlow({ ttlSeconds: 300, refresh })).rejects.toThrow(
      "refresh refused",
    );
    expect(screen.queryByText("auth.step_up.title")).not.toBeInTheDocument();
    expect(axiosPostMock).not.toHaveBeenCalled();
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

  it("asks for the authenticator code when the backend wants one", async () => {
    const user = userEvent.setup();
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );

    const flow = runStepUpFlow({ ttlSeconds: 300 });
    flow.catch(() => {});
    await screen.findByText("auth.step_up.title");

    axiosPostMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { code: "auth.two_factor.code_required", message: "Code needed." },
      },
    });
    await submitPassword(user);

    // The password was right: no error, the password stays, a code is asked.
    const codeLabel = "auth.two_factor.code_label";
    await user.type(await screen.findByLabelText(codeLabel), "000000");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("auth.step_up.password")).toHaveValue("hunter2");

    // A wrong code shows the error and clears only the code. (A reset
    // remounts the input, so it is looked up again.)
    axiosPostMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { code: "auth.two_factor.invalid_code", message: "Wrong code." },
      },
    });
    await user.click(screen.getByRole("button", { name: "auth.step_up.submit" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("auth.step_up.password")).toHaveValue("hunter2");
    expect(screen.getByLabelText(codeLabel)).toHaveValue("");

    axiosPostMock.mockResolvedValueOnce({
      data: { access: "sudo-token", ttl_seconds: 300 },
    });
    await user.type(screen.getByLabelText(codeLabel), "123456");
    await user.click(screen.getByRole("button", { name: "auth.step_up.submit" }));

    await expect(flow).resolves.toBe("sudo-token");
    expect(axiosPostMock).toHaveBeenLastCalledWith(
      "/api/auth/step-up/",
      { password: "hunter2", totp_code: "123456" },
      expect.anything(),
    );
  });

  it("shows a lockout in the app's own words and keeps the flow open", async () => {
    const user = userEvent.setup();
    render(
      <StepUpProvider>
        <div />
      </StepUpProvider>,
    );

    const flow = runStepUpFlow({ ttlSeconds: 300 });
    flow.catch(() => {});
    await screen.findByText("auth.step_up.title");

    const serverMessage =
      "Too many failed attempts. Try again later or reset your password.";
    axiosPostMock.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 429,
        data: { code: "auth.account_locked", message: serverMessage },
      },
    });
    await submitPassword(user);

    const lockedMessage = i18n.t("errors.auth.account_locked");
    expect(lockedMessage).not.toBe("errors.auth.account_locked");
    expect(await screen.findByText(lockedMessage)).toBeInTheDocument();
    expect(screen.queryByText(serverMessage)).not.toBeInTheDocument();
    // The modal stays up for a later try; the original action isn't failed.
    expect(screen.getByLabelText("auth.step_up.password")).toBeInTheDocument();
    expect(getAccessToken()).toBe("stale-token");
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
