/**
 * MemberDeliveryEditModal: the office dialog that moves one of a member's
 * deliveries to another station day or marks a joker on it. The real modal and
 * its form hook render; the generated commissioning client is the mocking
 * boundary, the station days and the tenant are stubbed, and the toasts are
 * recorded.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShareDelivery } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const notify = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("@shared/utils/notify", () => ({
  default: notify,
  registerAnnouncer: () => {},
  announcePolite: () => {},
}));

const saveDelivery = vi.hoisted(() =>
  vi.fn<(id: string, body: unknown) => Promise<unknown>>(),
);
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningShareDeliveryPartialUpdate: (id: string, body: unknown) =>
    saveDelivery(id, body),
}));

vi.mock("@hooks/index", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@hooks/index")>();
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  const stationDays = {
    deliveryStationDays: [
      { value: "sd-market", label: "Market (Tue)" },
      { value: "sd-farm", label: "Farm (Fri)" },
    ],
    loading: false,
  };
  return {
    ...actual,
    useTenant: () => tenant,
    useDeliveryStationDays: () => stationDays,
  };
});

import MemberDeliveryEditModal from "../MemberDeliveryEditModal";

const DELIVERY = {
  id: "delivery-7",
  year: 2026,
  delivery_week: 41,
  delivery_day_number: 1,
  delivery_station_day: "sd-market",
  delivery_station_name: "Market",
  joker_taken: false,
  donation_joker_taken: false,
  amount_of_jokers: 2,
  amount_of_donation_jokers: 0,
} as ShareDelivery;

function renderModal() {
  const onSuccess = vi.fn();
  const onCancel = vi.fn();
  render(
    <MemberDeliveryEditModal
      visible
      delivery={DELIVERY}
      onSuccess={onSuccess}
      onCancel={onCancel}
    />,
  );
  return { onSuccess, onCancel };
}

const dialog = () => screen.findByRole("dialog");

beforeEach(() => {
  saveDelivery.mockReset();
  notify.success.mockReset();
  notify.error.mockReset();
});

describe("saving a delivery", () => {
  it("saves once when Save is clicked and Enter follows while it saves", async () => {
    let finish: (value: unknown) => void = () => {};
    saveDelivery.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const user = userEvent.setup();
    const { onSuccess, onCancel } = renderModal();
    const modal = await dialog();

    const joker = within(modal).getByRole("checkbox", { name: "delivery.joker_taken" });
    await user.click(joker);
    await user.click(within(modal).getByRole("button", { name: "common.save" }));
    // Enter in the form while the save is still running.
    joker.focus();
    await user.keyboard("{Enter}");
    finish({});

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(saveDelivery).toHaveBeenCalledTimes(1);
    expect(saveDelivery).toHaveBeenCalledWith("delivery-7", {
      delivery_station_day: "sd-market",
      apply_to_future: false,
      joker_taken: true,
    });
    expect(notify.success).toHaveBeenCalledWith(
      "members.delivery_updated_successfully",
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("tells the office the server's reason when the save is refused", async () => {
    saveDelivery.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { message: "Week is read-only." } },
    });
    const user = userEvent.setup();
    const { onSuccess } = renderModal();
    const modal = await dialog();

    await user.click(within(modal).getByRole("button", { name: "common.save" }));

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("Week is read-only."),
    );
    expect(onSuccess).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("says the delivery wasn't updated when the server gives no reason", async () => {
    saveDelivery.mockRejectedValue(new Error("Network Error"));
    const user = userEvent.setup();
    renderModal();
    const modal = await dialog();

    await user.click(within(modal).getByRole("button", { name: "common.save" }));

    await waitFor(() =>
      expect(notify.error).toHaveBeenCalledWith("members.delivery_update_failed"),
    );
  });
});
