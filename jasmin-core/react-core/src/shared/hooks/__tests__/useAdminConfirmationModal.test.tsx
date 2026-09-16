/**
 * ``useAdminConfirmationModal`` hands an optional request body through to the
 * confirm call (the members and coop share confirm endpoints take
 * ``confirmed_at`` in onboarding mode). Boundary mocked: ``notify`` and the
 * api error helper.
 */
import React from "react";
import { describe, expect, it, vi } from "vitest";
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
vi.mock("@shared/utils", () => ({ notify: notifyMock }));
vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: () => "error message",
}));

import {
  useAdminConfirmationModal,
  type AdminConfirmableRecord,
} from "../useAdminConfirmationModal";

interface ConfirmBody {
  confirmed_at?: string;
}

const record: AdminConfirmableRecord = { key: "m-1", id: "m-1" };

function renderConfirmHook(
  confirmFn: (id: string, body?: ConfirmBody) => Promise<{ id: string }>,
) {
  return renderHook(() =>
    useAdminConfirmationModal<
      AdminConfirmableRecord,
      { id: string },
      ConfirmBody
    >({ confirmFn, successKey: "ok", errorKey: "failed" }),
  );
}

describe("useAdminConfirmationModal", () => {
  it("passes the body given to confirm on to confirmFn", async () => {
    const confirmFn = vi.fn().mockResolvedValue({ id: "m-1" });
    const { result } = renderConfirmHook(confirmFn);

    act(() => result.current.handleOpen(record));
    await act(async () => {
      await result.current.confirm({ confirmed_at: "2019-04-01" });
    });

    expect(confirmFn).toHaveBeenCalledWith("m-1", {
      confirmed_at: "2019-04-01",
    });
    expect(notifyMock.success).toHaveBeenCalledWith("ok");
  });

  it("calls confirmFn without a body when none is given", async () => {
    const confirmFn = vi.fn().mockResolvedValue({ id: "m-1" });
    const { result } = renderConfirmHook(confirmFn);

    act(() => result.current.handleOpen(record));
    await act(async () => {
      await result.current.confirm();
    });

    expect(confirmFn).toHaveBeenCalledWith("m-1", undefined);
  });

  it("hands the body and the server payload through handleConfirm", async () => {
    const confirmFn = vi.fn().mockResolvedValue({ id: "m-1" });
    const onConfirmed = vi.fn();
    const { result } = renderConfirmHook(confirmFn);

    act(() => result.current.handleOpen(record));
    await act(async () => {
      await result.current.handleConfirm(onConfirmed, {
        confirmed_at: "2020-02-03",
      });
    });

    expect(confirmFn).toHaveBeenCalledWith("m-1", {
      confirmed_at: "2020-02-03",
    });
    expect(onConfirmed).toHaveBeenCalledWith({ id: "m-1" });
    expect(result.current.isOpen).toBe(false);
  });
});
