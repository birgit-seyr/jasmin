/**
 * ``usePaperReceivedToggle`` stores the day the paper arrived as today's local
 * date. Boundary mocked: ``notify``.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const notifyMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@shared/utils", async () => ({
  notify: notifyMock,
  todayApiDate: (
    await vi.importActual<typeof import("@shared/utils/apiDate")>(
      "@shared/utils/apiDate",
    )
  ).todayApiDate,
}));

import { usePaperReceivedToggle } from "../usePaperReceivedToggle";

function renderToggle(patch: (id: string, value: string | null) => Promise<unknown>) {
  return renderHook(() =>
    usePaperReceivedToggle({
      initialValue: false,
      id: "m-1",
      patch,
      onPatched: () => {},
    }),
  );
}

describe("usePaperReceivedToggle", () => {
  beforeEach(() => {
    vi.stubEnv("TZ", "Europe/Berlin");
    vi.useFakeTimers({ toFake: ["Date"] });
    // 00:30 in Berlin on 16 October is still 15 October in UTC.
    vi.setSystemTime(new Date("2026-10-15T22:30:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it("stores today's local date when the paper is ticked as received", async () => {
    const patch = vi.fn(() => Promise.resolve({}));
    const { result } = renderToggle(patch);

    await act(() => result.current.handlePaperToggle(true));

    expect(patch).toHaveBeenCalledWith("m-1", "2026-10-16");
    expect(result.current.paperReceived).toBe(true);
  });

  it("clears the date when the tick is taken away", async () => {
    const patch = vi.fn(() => Promise.resolve({}));
    const { result } = renderToggle(patch);

    await act(() => result.current.handlePaperToggle(false));

    expect(patch).toHaveBeenCalledWith("m-1", null);
  });
});
