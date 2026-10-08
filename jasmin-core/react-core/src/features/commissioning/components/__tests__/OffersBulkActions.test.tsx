/**
 * OffersBulkActions: the button row above the offers grid. It finalizes the
 * selected offers, copies them to next week, or copies them into each other
 * offer group of the week — the copies only after the office confirms.
 * Rendered with the real BulkActionButton and Popconfirm; the generated
 * commissioning client is the mocking boundary and answers as the backend's
 * bulk views do.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BulkCopyOffersResponse, BulkFinalizeResponse } from "@shared/api/generated/models";
import type { useOffersData } from "@features/commissioning/hooks/useOffersData";

// Shows the values a label is interpolated with after its key, so each
// offer group's button and message can be told apart.
const i18nMock = vi.hoisted(() => ({
  t: (key: string, options?: unknown) => {
    if (typeof options === "string") return options;
    if (options && typeof options === "object") {
      const values = Object.entries(options as Record<string, unknown>)
        .map(([name, value]) => `${name}=${String(value)}`);
      if (values.length > 0) return `${key} ${values.join(" ")}`;
    }
    return key;
  },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: i18nMock.t,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { notify, api } = vi.hoisted(() => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  api: { finalize: vi.fn(), copyToNextWeek: vi.fn(), copyToOfferGroup: vi.fn() },
}));

vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  notify,
}));

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningBulkFinalizeCreate: (payload: unknown) => api.finalize(payload),
  commissioningBulkCopyOffersToNextWeekCreate: (payload: unknown) => api.copyToNextWeek(payload),
  commissioningBulkCopyOffersToOfferGroupCreate: (payload: unknown) => api.copyToOfferGroup(payload),
}));

import OffersBulkActions from "../OffersBulkActions";

// ── Fixtures ────────────────────────────────────────────────────────────────

type OfferGroups = ReturnType<typeof useOffersData>["otherOfferGroups"];

// Shaped as useOfferGroups hands them over: each row carries its id as the
// option ``value`` too.
const MARKET = { id: "group-market", value: "group-market", label: "Market stall", number: 2, name: "Market stall" };
const SHOP = { id: "group-shop", value: "group-shop", label: "Farm shop", number: 3, name: "Farm shop" };
const OTHER_GROUPS: OfferGroups = [MARKET, SHOP];

const SELECTED = ["offer-carrots", "offer-lemons"];

const finalized = (fields: Partial<BulkFinalizeResponse> = {}): BulkFinalizeResponse => ({
  message: "Finalization completed",
  finalized_count: 2,
  already_finalized_count: 0,
  total_requested: 2,
  errors: [],
  ...fields,
});

const copied = (fields: Partial<BulkCopyOffersResponse> = {}): BulkCopyOffersResponse => ({
  total_requested: 2,
  total_copied: 2,
  skipped_count: 0,
  copied_offers: ["offer-new-1", "offer-new-2"],
  ...fields,
});

/** A rejected request as axios hands it over, carrying the server's body. */
const httpError = (status: number, data: Record<string, unknown>) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

const onClearSelection = vi.fn();
const onInvalidate = vi.fn();

beforeEach(() => {
  Object.values(notify).forEach((fn) => fn.mockReset());
  Object.values(api).forEach((fn) => fn.mockReset());
  onClearSelection.mockReset();
  onInvalidate.mockReset();
  api.finalize.mockResolvedValue(finalized());
  api.copyToNextWeek.mockResolvedValue(copied());
  api.copyToOfferGroup.mockResolvedValue(copied());
});

// ── Helpers ─────────────────────────────────────────────────────────────────

function renderActions({
  selected = SELECTED,
  otherOfferGroups = OTHER_GROUPS,
}: { selected?: string[]; otherOfferGroups?: OfferGroups } = {}) {
  const user = userEvent.setup();
  render(
    <OffersBulkActions
      selectedRowKeys={selected}
      onClearSelection={onClearSelection}
      onInvalidate={onInvalidate}
      otherOfferGroups={otherOfferGroups}
      selectedYear={2026}
      selectedWeek={42}
    />,
  );
  return { user };
}

const FINALIZE = "commissioning.finalize";
const COPY_TO_NEXT_WEEK = "commissioning.copy_selected_to_next_week";
const copyToGroup = (name: string) => `commissioning.copy_to_offer_group name=${name}`;

const button = (name: string) => screen.getByRole("button", { name });

type User = ReturnType<typeof userEvent.setup>;

/** Clicks a copy button and confirms the question it asks. */
async function confirm(user: User, name: string, question: string) {
  await user.click(button(name));
  expect(await screen.findByText(question)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "common.yes" }));
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("OffersBulkActions buttons", () => {
  it("offers finalizing, copying to next week and copying into each other offer group", () => {
    renderActions();

    expect(screen.getAllByRole("button").map((element) => element.textContent)).toEqual([
      FINALIZE,
      COPY_TO_NEXT_WEEK,
      copyToGroup("Market stall"),
      copyToGroup("Farm shop"),
    ]);
  });

  it("offers no group copies when the week has no other offer group", () => {
    renderActions({ otherOfferGroups: [] as OfferGroups });

    expect(screen.getAllByRole("button").map((element) => element.textContent)).toEqual([
      FINALIZE,
      COPY_TO_NEXT_WEEK,
    ]);
  });

  it("locks every action while no offer is selected", async () => {
    const { user } = renderActions({ selected: [] });

    for (const name of [FINALIZE, COPY_TO_NEXT_WEEK, copyToGroup("Market stall"), copyToGroup("Farm shop")]) {
      expect(button(name)).toBeDisabled();
    }
    await user.click(button(COPY_TO_NEXT_WEEK));

    expect(screen.queryByText("commissioning.confirm_offers_copy_title")).not.toBeInTheDocument();
    expect(api.finalize).not.toHaveBeenCalled();
    expect(api.copyToNextWeek).not.toHaveBeenCalled();
    expect(api.copyToOfferGroup).not.toHaveBeenCalled();
  });
});

describe("OffersBulkActions finalizing", () => {
  it("finalizes the selected offers, then clears the selection and refreshes the grid", async () => {
    const { user } = renderActions();

    await user.click(button(FINALIZE));

    await waitFor(() => expect(onInvalidate).toHaveBeenCalledTimes(1));
    expect(api.finalize).toHaveBeenCalledTimes(1);
    expect(api.finalize).toHaveBeenCalledWith({
      ids: SELECTED,
      model: "offer",
      app_label: "commissioning",
    });
    expect(onClearSelection).toHaveBeenCalledTimes(1);
    expect(notify.warning).not.toHaveBeenCalled();
    expect(notify.error).not.toHaveBeenCalled();
  });

  it("warns about the offers the server could not finalize and still refreshes the grid", async () => {
    api.finalize.mockResolvedValue(
      finalized({
        finalized_count: 1,
        errors: [{ id: "offer-lemons", error: "Offer has no price" }],
      }),
    );
    const { user } = renderActions();

    await user.click(button(FINALIZE));

    await waitFor(() => expect(onInvalidate).toHaveBeenCalledTimes(1));
    expect(notify.warning).toHaveBeenCalledTimes(1);
    expect(notify.warning.mock.calls[0][0]).toContain("Offer has no price");
    expect(notify.error).not.toHaveBeenCalled();
    expect(onClearSelection).toHaveBeenCalledTimes(1);
  });

  it("shows the server's reason when finalizing fails and keeps the selection", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.finalize.mockRejectedValue(
      httpError(404, { code: "not_found", message: "No objects found with provided IDs" }),
    );
    const { user } = renderActions();

    await user.click(button(FINALIZE));

    // The error's code carries the office's own words for it.
    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("Datensatz nicht gefunden."));
    expect(onClearSelection).not.toHaveBeenCalled();
    expect(onInvalidate).not.toHaveBeenCalled();
    expect(button(FINALIZE)).toBeEnabled();
  });
});

describe("OffersBulkActions copying to next week", () => {
  it("copies nothing until the office confirms", async () => {
    const { user } = renderActions();

    await user.click(button(COPY_TO_NEXT_WEEK));
    expect(await screen.findByText("commissioning.confirm_offers_copy_title")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "common.cancel" }));

    expect(api.copyToNextWeek).not.toHaveBeenCalled();
    expect(onClearSelection).not.toHaveBeenCalled();
  });

  it("copies the selected offers once confirmed, says so and clears the selection", async () => {
    const { user } = renderActions();

    await confirm(user, COPY_TO_NEXT_WEEK, "commissioning.confirm_offers_copy_title");

    await waitFor(() => expect(notify.success).toHaveBeenCalledWith("commissioning.copied_to_next_week count=2 skipped=0"));
    expect(api.copyToNextWeek).toHaveBeenCalledTimes(1);
    expect(api.copyToNextWeek).toHaveBeenCalledWith({ ids: SELECTED });
    expect(onClearSelection).toHaveBeenCalledTimes(1);
    expect(api.copyToOfferGroup).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the copy fails and keeps the selection", async () => {
    api.copyToNextWeek.mockRejectedValue(
      httpError(400, { code: "validation_error", message: "Offer offer-lemons does not exist" }),
    );
    const { user } = renderActions();

    await confirm(user, COPY_TO_NEXT_WEEK, "commissioning.confirm_offers_copy_title");

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("Offer offer-lemons does not exist"));
    expect(notify.success).not.toHaveBeenCalled();
    expect(onClearSelection).not.toHaveBeenCalled();
  });

  it("falls back to the copy-failed message when the failure carries no reason", async () => {
    api.copyToNextWeek.mockRejectedValue({ isAxiosError: true, message: "", response: { status: 500, data: {} } });
    const { user } = renderActions();

    await confirm(user, COPY_TO_NEXT_WEEK, "commissioning.confirm_offers_copy_title");

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("commissioning.copy_failed"));
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("does not report offers as copied when next week already had all of them", async () => {
    api.copyToNextWeek.mockResolvedValue(copied({ total_copied: 0, skipped_count: 2, copied_offers: [] }));
    const { user } = renderActions();

    await confirm(user, COPY_TO_NEXT_WEEK, "commissioning.confirm_offers_copy_title");

    await waitFor(() => expect(notify.warning).toHaveBeenCalledTimes(1));
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("counts the offers copied and the ones next week already had", async () => {
    api.copyToNextWeek.mockResolvedValue(copied({ total_copied: 1, skipped_count: 1, copied_offers: ["offer-new-1"] }));
    const { user } = renderActions();

    await confirm(user, COPY_TO_NEXT_WEEK, "commissioning.confirm_offers_copy_title");

    await waitFor(() =>
      expect(notify.success).toHaveBeenCalledWith("commissioning.copied_to_next_week_some_skipped count=1 skipped=1"),
    );
    expect(notify.warning).not.toHaveBeenCalled();
  });
});

describe("OffersBulkActions copying into another offer group", () => {
  it("copies the selected offers into the chosen group for the shown week", async () => {
    const { user } = renderActions();

    await confirm(
      user,
      copyToGroup("Farm shop"),
      "commissioning.confirm_copy_to_offer_group offerGroup=Farm shop",
    );

    await waitFor(() =>
      expect(notify.success).toHaveBeenCalledWith("commissioning.copied_to_offer_group count=2 skipped=0 offerGroup=Farm shop"),
    );
    expect(api.copyToOfferGroup).toHaveBeenCalledTimes(1);
    expect(api.copyToOfferGroup).toHaveBeenCalledWith({
      ids: SELECTED,
      year: 2026,
      delivery_week: 42,
      offer_group: "group-shop",
    });
    expect(onClearSelection).toHaveBeenCalledTimes(1);
    expect(api.copyToNextWeek).not.toHaveBeenCalled();
  });

  it("warns instead of reporting a copy when the group already had every offer", async () => {
    api.copyToOfferGroup.mockResolvedValue(copied({ total_copied: 0, skipped_count: 2, copied_offers: [] }));
    const { user } = renderActions();

    await confirm(
      user,
      copyToGroup("Farm shop"),
      "commissioning.confirm_copy_to_offer_group offerGroup=Farm shop",
    );

    await waitFor(() =>
      expect(notify.warning).toHaveBeenCalledWith(
        "commissioning.copied_to_offer_group_none count=0 skipped=2 offerGroup=Farm shop",
      ),
    );
    expect(notify.success).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the group copy fails and keeps the selection", async () => {
    api.copyToOfferGroup.mockRejectedValue(
      httpError(400, { code: "bulk_copy_offers.offer_group_required", message: "offer_group is required" }),
    );
    const { user } = renderActions();

    await confirm(
      user,
      copyToGroup("Market stall"),
      "commissioning.confirm_copy_to_offer_group offerGroup=Market stall",
    );

    await waitFor(() => expect(notify.error).toHaveBeenCalledWith("Bitte eine Angebotsgruppe angeben."));
    expect(api.copyToOfferGroup).toHaveBeenCalledWith(expect.objectContaining({ offer_group: "group-market" }));
    expect(notify.success).not.toHaveBeenCalled();
    expect(onClearSelection).not.toHaveBeenCalled();
  });
});
