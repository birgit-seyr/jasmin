/**
 * The phone's harvest confirmation: the dialog and the hook that holds its
 * amount, wired as HarvestingList wires them. The generated client is the
 * mocking boundary. The tenant sets no number format, so the field writes
 * numbers the German way, with a decimal comma.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@hooks/configuration/useTenant", async () => {
  const { makeUseTenantMock } = await import("@/test/tenantMock");
  const tenant = makeUseTenantMock();
  return { useTenant: () => tenant };
});

const { saveHarvest, notify } = vi.hoisted(() => ({
  saveHarvest: vi.fn(),
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  notify,
}));
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningHarvestPartialUpdate: (id: string, body: unknown) =>
    saveHarvest(id, body),
}));

import { HarvestConfirmationModal } from "../HarvestConfirmationModal";
import { useHarvestConfirmation } from "../useHarvestConfirmation";

const TUESDAY = 1; // Backend day numbers: 0 = Monday … 6 = Sunday.
const CONFIRM = "commissioning.actual_harvest";
const SET_AS_EXPECTED = "commissioning.set_as_expected_harvest";

/** The dialog and its hook, wired as HarvestingList wires them. */
function HarvestConfirmation({ row }: { row: TableRecord }) {
  const confirmation = useHarvestConfirmation({
    selectedYear: 2026,
    selectedWeek: 41,
    selectedDay: TUESDAY,
    fallbackWeek: 41,
    onSaved: () => {},
  });
  return (
    <>
      <button type="button" onClick={() => confirmation.open(row)}>
        Confirm the harvest
      </button>
      <HarvestConfirmationModal
        record={confirmation.record}
        amount={confirmation.amount}
        saving={confirmation.saving}
        onChangeAmount={confirmation.setAmount}
        onCancel={confirmation.close}
        onConfirm={confirmation.confirm}
      />
    </>
  );
}

/** A phone card's row with nothing harvested yet, as the harvesting list computes it. */
const leeksExpecting = (expected: number): TableRecord => ({
  key: "h-leeks",
  id: "h-leeks",
  share_article_name: "Leeks",
  computed_article_with_size: "Leeks",
  computed_total_amount: expected,
  computed_unit_label: "kg",
  harvest_amount: null,
});

beforeEach(() => {
  saveHarvest.mockReset().mockResolvedValue({});
  Object.values(notify).forEach((fn) => fn.mockReset());
});

describe("confirming the expected harvest untouched", () => {
  it.each([
    ["an expected amount summed in floats", 10.2 - 3.4, "6,80", 6.8],
    ["an expected amount planned to three decimals", 0.875, "0,88", 0.88],
    // Half up on the decimals the field shows, not on the float: 1.005 is 1.00499… as a float.
    ["an expected amount on a half", 1.005, "1,01", 1.01],
  ])("starts from %s at two decimals, as the field shows it, and saves that", async (_case, expected, shown, saved) => {
    const user = userEvent.setup();
    render(<HarvestConfirmation row={leeksExpecting(expected)} />);

    await user.click(screen.getByRole("button", { name: "Confirm the harvest" }));
    const dialog = await screen.findByRole("dialog", { name: CONFIRM });
    expect(within(dialog).getByRole("spinbutton", { name: CONFIRM })).toHaveValue(shown);
    await user.click(within(dialog).getByRole("button", { name: SET_AS_EXPECTED }));

    await waitFor(() => expect(saveHarvest).toHaveBeenCalledTimes(1));
    expect(saveHarvest).toHaveBeenCalledWith("h-leeks", {
      amount: saved,
      year: 2026,
      delivery_week: 41,
      day_number: TUESDAY,
    });
  });
});

describe("a refused confirmation", () => {
  async function confirmLeeks() {
    const user = userEvent.setup();
    render(<HarvestConfirmation row={leeksExpecting(4)} />);
    await user.click(screen.getByRole("button", { name: "Confirm the harvest" }));
    const dialog = await screen.findByRole("dialog", { name: CONFIRM });
    await user.click(within(dialog).getByRole("button", { name: SET_AS_EXPECTED }));
    await waitFor(() => expect(notify.error).toHaveBeenCalledTimes(1));
    return dialog;
  }

  it("tells the user the server's reason and keeps the dialog open", async () => {
    saveHarvest.mockRejectedValue({
      isAxiosError: true,
      response: { status: 400, data: { message: "Week is read-only." } },
    });

    const dialog = await confirmLeeks();

    expect(notify.error).toHaveBeenCalledWith("Week is read-only.");
    expect(dialog).toBeVisible();
    expect(within(dialog).getByRole("spinbutton", { name: CONFIRM })).toHaveValue("4,00");
  });

  it("says the amount wasn't saved when the server gives no reason", async () => {
    saveHarvest.mockRejectedValue(new Error("Network Error"));

    await confirmLeeks();

    expect(notify.error).toHaveBeenCalledWith("commissioning.harvest_save_failed");
  });
});
