/**
 * ``useAbosApiFunctions``: an over-capacity save on the Abos grid is retried as
 * a waiting-list entry, except while the tenant's waiting list is off or while
 * onboarding mode is on, where the capacity error reaches the table instead.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const createMock = vi.fn();
const partialUpdateMock = vi.fn();
const destroyMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningAbosCreate: (...args: unknown[]) => createMock(...args),
  commissioningAbosPartialUpdate: (...args: unknown[]) =>
    partialUpdateMock(...args),
  commissioningAbosDestroy: (...args: unknown[]) => destroyMock(...args),
}));

const notifyInfoMock = vi.fn();
vi.mock("@shared/utils", () => ({
  notify: { info: (...args: unknown[]) => notifyInfoMock(...args) },
}));

import { useAbosApiFunctions } from "../useAbosApiFunctions";

const overCapacityError = (code: string) => ({
  isAxiosError: true,
  response: { status: 409, data: { code, message: "full" } },
});

const ROW = { key: -1, member: "member-1", valid_from: "2026-06-01" };

function renderApiFunctions({
  allowsWaitingList = true,
  onboardingMode = false,
}: { allowsWaitingList?: boolean; onboardingMode?: boolean } = {}) {
  const invalidateData = vi.fn();
  const { result } = renderHook(() =>
    useAbosApiFunctions({ invalidateData, allowsWaitingList, onboardingMode }),
  );
  return { apiFunctions: result.current, invalidateData };
}

describe("useAbosApiFunctions", () => {
  beforeEach(() => {
    createMock.mockReset();
    partialUpdateMock.mockReset();
    destroyMock.mockReset();
    notifyInfoMock.mockReset();
  });

  it("retries an over-capacity create on the waiting list", async () => {
    createMock
      .mockRejectedValueOnce(overCapacityError("delivery_station.over_capacity"))
      .mockResolvedValueOnce({ id: "sub-1", on_waiting_list: true });
    const { apiFunctions, invalidateData } = renderApiFunctions();

    const result = await apiFunctions.create!(ROW);

    expect(createMock).toHaveBeenCalledTimes(2);
    expect(createMock.mock.calls[1][0]).toEqual({
      ...ROW,
      on_waiting_list: true,
    });
    expect(result).toEqual({ data: { id: "sub-1", on_waiting_list: true } });
    expect(notifyInfoMock).toHaveBeenCalledWith(
      "abos.waiting_listed_station_full",
    );
    expect(invalidateData).toHaveBeenCalledTimes(1);
  });

  it("shows the capacity error on create while onboarding mode is on", async () => {
    const error = overCapacityError("share_type_variation.over_capacity");
    createMock.mockRejectedValueOnce(error);
    const { apiFunctions, invalidateData } = renderApiFunctions({
      onboardingMode: true,
    });

    await expect(apiFunctions.create!(ROW)).rejects.toBe(error);

    expect(createMock).toHaveBeenCalledTimes(1);
    expect(notifyInfoMock).not.toHaveBeenCalled();
    expect(invalidateData).not.toHaveBeenCalled();
  });

  it("shows the capacity error on update while onboarding mode is on", async () => {
    const error = overCapacityError("delivery_station.over_capacity");
    partialUpdateMock.mockRejectedValueOnce(error);
    const { apiFunctions, invalidateData } = renderApiFunctions({
      onboardingMode: true,
    });

    await expect(apiFunctions.update!("sub-1", ROW)).rejects.toBe(error);

    expect(partialUpdateMock).toHaveBeenCalledTimes(1);
    expect(invalidateData).not.toHaveBeenCalled();
  });

  it("retries an over-capacity update on the waiting list while onboarding mode is off", async () => {
    partialUpdateMock
      .mockRejectedValueOnce(
        overCapacityError("share_type_variation.over_capacity"),
      )
      .mockResolvedValueOnce({ id: "sub-1", on_waiting_list: true });
    const { apiFunctions } = renderApiFunctions();

    await apiFunctions.update!("sub-1", ROW);

    expect(partialUpdateMock).toHaveBeenCalledTimes(2);
    expect(partialUpdateMock.mock.calls[1]).toEqual([
      "sub-1",
      { ...ROW, on_waiting_list: true },
    ]);
    expect(notifyInfoMock).toHaveBeenCalledWith(
      "abos.waiting_listed_variation_full",
    );
  });

  it("shows the capacity error while the waiting list is off", async () => {
    const error = overCapacityError("delivery_station.over_capacity");
    createMock.mockRejectedValueOnce(error);
    const { apiFunctions } = renderApiFunctions({ allowsWaitingList: false });

    await expect(apiFunctions.create!(ROW)).rejects.toBe(error);
    expect(createMock).toHaveBeenCalledTimes(1);
  });

  it("never retries an error that is not about capacity", async () => {
    const error = {
      isAxiosError: true,
      response: { status: 400, data: { code: "subscription.start_too_soon" } },
    };
    createMock.mockRejectedValueOnce(error);
    const { apiFunctions } = renderApiFunctions();

    await expect(apiFunctions.create!(ROW)).rejects.toBe(error);
    expect(createMock).toHaveBeenCalledTimes(1);
  });
});
