/**
 * Solidarity-pricing gating test for ``NewSubscriptionModal`` (audit SOL-10).
 *
 * The modal lets a MEMBER set their own ``price_per_delivery`` only when the
 * tenant has ``allows_solidarity_pricing`` on; otherwise the field is disabled
 * and the price is NOT sent (the backend forces the reference price). The OFFICE
 * path always sends the price. The audit flagged zero coverage for this gate, so
 * a refactor of the ``isMemberOnly && !allowsSolidarity`` condition (or the
 * spread-when-on payload) could silently let a member submit a custom price with
 * solidarity off. These tests pin the user-visible gate.
 *
 * Boundary mocked: every ``@hooks/index`` hook (the modal's data layer),
 * ``useRoles`` (member vs office), the two generated create fns, ``notify`` and
 * ``getErrorMessage``. AntD ``InputNumber`` and ``DatePicker`` are stubbed to
 * plain controlled inputs (jsdom-friendly + lets us read the ``disabled`` /
 * ``min`` props directly); the real AntD ``Form`` / ``Modal`` run unmocked.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dayjs from "dayjs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// ── Roles: member vs office, swappable per test ────────────────────────────
const rolesMock = vi.fn();
vi.mock("@shared/auth", () => ({
  useRoles: () => rolesMock(),
}));

// ── Generated create fns (the boundary under assertion) ────────────────────
const subscribeCreateMock = vi.fn();
const abosCreateMock = vi.fn();
vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  commissioningMySubscriptionsSubscribeCreate: (...args: unknown[]) =>
    subscribeCreateMock(...args),
  commissioningAbosCreate: (...args: unknown[]) => abosCreateMock(...args),
}));

const notifySuccessMock = vi.fn();
const notifyErrorMock = vi.fn();
vi.mock("@shared/utils", () => ({
  notify: {
    success: (...a: unknown[]) => notifySuccessMock(...a),
    error: (...a: unknown[]) => notifyErrorMock(...a),
  },
}));
vi.mock("@shared/utils/apiError", () => ({
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

// ── Tenant settings toggle ─────────────────────────────────────────────────
const getSettingMock = vi.fn();

// ── Data hooks ──────────────────────────────────────────────────────────────
// One variation carrying a reference price + an explicit solidarity floor; the
// "min" assertion checks the floor is preferred over the reference.
const VARIATION = {
  value: "stv-1",
  label: "Gemüse M",
  share_type: "st-1",
  share_type_name: "Gemüse",
  size: "M",
  sort_order: 0,
  valid_from: "2026-01-05",
  active_price_per_delivery: "10.00",
  active_solidarity_min_price_per_delivery: "7.00",
};

vi.mock("@hooks/index", () => ({
  useShareTypes: () => ({
    shareTypes: [{ id: "st-1", value: "st-1", delivery_cycle: null }],
  }),
  useAllShareTypeVariations: () => ({ shareTypeVariations: [VARIATION] }),
  usePaymentCycles: () => ({
    paymentCycles: [{ value: "cycle-1", label: "Monatlich" }],
  }),
  useDeliveryStationDays: () => ({
    deliveryStationDays: [
      { value: "dsd-1", label: "Station A", capacity: null },
    ],
    loading: false,
  }),
  useCurrency: () => ({ currencySymbol: "€" }),
  useDateFormat: () => ({
    dateFormat: "DD.MM.YYYY",
    formatDate: (d: dayjs.Dayjs) => d.format("DD.MM.YYYY"),
  }),
  useShareVariationSizeOptions: () => ({
    getShareVariationSizeLabel: (s: string) => s,
  }),
  useTenant: () => ({ getSetting: getSettingMock }),
  useSubscriptionTerm: () => ({
    allowsTrial: false,
    endOfSeason: false,
    endAfterOneYear: false,
    computeValidUntil: () => null,
    isValidUntilAuto: () => false,
    // The earliest sellable start — the modal reads this for the default
    // pricing date (before valid_from is picked). A fixed future Monday.
    earliestValidFrom: dayjs().startOf("isoWeek").add(2, "week"),
    // Permit any Monday on/after a fixed past date so the test's chosen
    // valid_from validates regardless of when the suite runs.
    disabledValidFromDate: (current: unknown) =>
      !!current && (current as dayjs.Dayjs).day() !== 1,
  }),
}));

// ── AntD InputNumber / DatePicker stubs ────────────────────────────────────
// Plain controlled inputs so the real AntD Form drives them, the
// ``disabled``/``min`` props are readable from the DOM, and value coercion to
// ``number``/``Dayjs`` matches what the modal expects out of each field.
vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  const StubInputNumber = ({
    value,
    onChange,
    disabled,
    min,
    id,
  }: {
    value?: number;
    onChange?: (v: number | null) => void;
    disabled?: boolean;
    min?: number;
    id?: string;
  }) => (
    <input
      // ``id`` is injected by AntD Form.Item from the field ``name`` — both the
      // quantity + price fields render this stub, so tests target by id.
      id={id}
      data-disabled={String(Boolean(disabled))}
      data-min={String(min)}
      disabled={disabled}
      value={value ?? ""}
      onChange={(e) =>
        onChange?.(e.target.value === "" ? null : Number(e.target.value))
      }
    />
  );
  const StubDatePicker = ({
    value,
    onChange,
    id,
  }: {
    value?: dayjs.Dayjs | null;
    onChange?: (d: dayjs.Dayjs | null) => void;
    id?: string;
  }) => (
    <input
      id={id}
      value={value ? value.format("YYYY-MM-DD") : ""}
      onChange={(e) =>
        onChange?.(e.target.value ? dayjs(e.target.value) : null)
      }
    />
  );
  return { ...actual, InputNumber: StubInputNumber, DatePicker: StubDatePicker };
});

import NewSubscriptionModal from "../NewSubscriptionModal";

// Both the quantity + price fields render the stubbed InputNumber, and both
// valid_from + valid_until render the stubbed DatePicker. AntD Form.Item wires
// the field ``name`` onto the input ``id``, so target by id.
function field(id: string): HTMLInputElement {
  const el = document.getElementById(id) as HTMLInputElement | null;
  if (!el) throw new Error(`field #${id} not found`);
  return el;
}
const priceField = () => field("price_per_delivery");
const validFromField = () => field("valid_from");

// A future Monday — a valid valid_from by the (relaxed) term rule.
const futureMonday = dayjs()
  .startOf("isoWeek")
  .add(4, "week")
  .format("YYYY-MM-DD");

function renderModal() {
  const onSuccess = vi.fn();
  const onCancel = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <NewSubscriptionModal
        visible
        memberId="m-1"
        onCancel={onCancel}
        onSuccess={onSuccess}
      />
    </QueryClientProvider>,
  );
  return { onSuccess, onCancel };
}

/** Pick the only variation card → advances to the details form. The size
 *  label "M" appears twice inside the card (placeholder + strong text); click
 *  the enclosing ``.ant-card`` (which carries the onClick) of the first. */
function selectVariation() {
  const label = screen.getAllByText("M")[0];
  const card = label.closest(".ant-card");
  if (!card) throw new Error("variation card not found");
  fireEvent.click(card);
}

/** Fill the required date + (optional) price fields so validateFields passes.
 *  Station + payment-cycle selects are driven separately in each test. */
function fillRequiredFields(price?: string) {
  fireEvent.change(validFromField(), { target: { value: futureMonday } });
  if (price !== undefined) {
    fireEvent.change(priceField(), { target: { value: price } });
  }
}

beforeEach(() => {
  rolesMock.mockReset();
  getSettingMock.mockReset();
  subscribeCreateMock.mockReset().mockResolvedValue(undefined);
  abosCreateMock.mockReset().mockResolvedValue(undefined);
  notifySuccessMock.mockReset();
  notifyErrorMock.mockReset();
});

describe("NewSubscriptionModal — solidarity price gating", () => {
  it("member + solidarity ON: price field enabled, min is the solidarity floor", () => {
    rolesMock.mockReturnValue({ isMemberOnly: true });
    getSettingMock.mockImplementation((k: string, fb?: unknown) =>
      k === "allows_solidarity_pricing" ? true : fb,
    );

    renderModal();
    selectVariation();

    const priceInput = priceField();
    expect(priceInput).toHaveAttribute("data-disabled", "false");
    // floor (7.00) wins over the reference (10.00).
    expect(priceInput).toHaveAttribute("data-min", "7");
  });

  it("member + solidarity OFF: price field disabled", () => {
    rolesMock.mockReturnValue({ isMemberOnly: true });
    getSettingMock.mockImplementation((k: string, fb?: unknown) =>
      k === "allows_solidarity_pricing" ? false : fb,
    );

    renderModal();
    selectVariation();

    const priceInput = priceField();
    expect(priceInput).toHaveAttribute("data-disabled", "true");
    // No solidarity floor → min falls back to 0.
    expect(priceInput).toHaveAttribute("data-min", "0");
  });

  it("member + solidarity ON: sends price_per_delivery as a string", async () => {
    rolesMock.mockReturnValue({ isMemberOnly: true });
    getSettingMock.mockImplementation((k: string, fb?: unknown) =>
      k === "allows_solidarity_pricing" ? true : fb,
    );

    renderModal();
    selectVariation();
    fillRequiredFields("8");
    // Station + payment cycle selects — set via the form items' comboboxes.
    fireEvent.mouseDown(screen.getByText("delivery.select_station"));
    fireEvent.click(await screen.findByText("Station A"));
    fireEvent.mouseDown(screen.getByText("abos.select_payment_cycle"));
    fireEvent.click(await screen.findByText("Monatlich"));

    fireEvent.click(screen.getByText("common.save"));

    await waitFor(() => expect(subscribeCreateMock).toHaveBeenCalledTimes(1));
    const payload = subscribeCreateMock.mock.calls[0][0];
    expect(payload.price_per_delivery).toBe("8");
    expect(typeof payload.price_per_delivery).toBe("string");
    expect(abosCreateMock).not.toHaveBeenCalled();
  });

  it("member + solidarity OFF: omits price_per_delivery from the payload", async () => {
    rolesMock.mockReturnValue({ isMemberOnly: true });
    getSettingMock.mockImplementation((k: string, fb?: unknown) =>
      k === "allows_solidarity_pricing" ? false : fb,
    );

    renderModal();
    selectVariation();
    // The variation select pre-fills the price (10.00) so the disabled+required
    // field still validates; we don't touch it.
    fillRequiredFields();
    fireEvent.mouseDown(screen.getByText("delivery.select_station"));
    fireEvent.click(await screen.findByText("Station A"));
    fireEvent.mouseDown(screen.getByText("abos.select_payment_cycle"));
    fireEvent.click(await screen.findByText("Monatlich"));

    fireEvent.click(screen.getByText("common.save"));

    await waitFor(() => expect(subscribeCreateMock).toHaveBeenCalledTimes(1));
    const payload = subscribeCreateMock.mock.calls[0][0];
    expect("price_per_delivery" in payload).toBe(false);
  });

  it("office path: price field enabled and always sent, regardless of toggle", async () => {
    rolesMock.mockReturnValue({ isMemberOnly: false });
    // Solidarity OFF — office still sends the price.
    getSettingMock.mockImplementation((k: string, fb?: unknown) =>
      k === "allows_solidarity_pricing" ? false : fb,
    );

    renderModal();
    selectVariation();

    const priceInput = priceField();
    // Office is never the member-only branch → field stays enabled.
    expect(priceInput).toHaveAttribute("data-disabled", "false");

    fillRequiredFields("12");
    fireEvent.mouseDown(screen.getByText("delivery.select_station"));
    fireEvent.click(await screen.findByText("Station A"));
    fireEvent.mouseDown(screen.getByText("abos.select_payment_cycle"));
    fireEvent.click(await screen.findByText("Monatlich"));

    fireEvent.click(screen.getByText("common.save"));

    await waitFor(() => expect(abosCreateMock).toHaveBeenCalledTimes(1));
    const payload = abosCreateMock.mock.calls[0][0];
    expect(payload.price_per_delivery).toBe("12");
    expect(subscribeCreateMock).not.toHaveBeenCalled();
  });
});
