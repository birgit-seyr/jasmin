/**
 * Tier-4 seam test for ``OrderAmountCell``.
 *
 * The component has four render branches called out in the test plan:
 *   1. read-only           → static Tag (or "-" when nothing ordered)
 *   2. finalized + existing → green Tag, no inputs
 *   3. editable + existing  → Input + "Update" button (PATCH path)
 *   4. not-yet-ordered      → Input + "Add" button (POST path)
 *
 * The cell is pure-presentational: we assert what it renders for each
 * branch and that the right callbacks fire on user interaction.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

import OrderAmountCell from "../OrderAmountCell";
import type { CustomerOrderRow } from "@features/customer/types";

// ── Fixtures ────────────────────────────────────────────────────────────────

const OFFER_ID = "offer-1";
const ORDER_CONTENT_ID = "oc-7";

/** Fixture helper: the cell only reads a handful of row fields. */
const makeRow = (row: Partial<CustomerOrderRow>) => row as CustomerOrderRow;

function makeProps(overrides: Partial<Parameters<typeof OrderAmountCell>[0]> = {}) {
  return {
    record: makeRow({ id: OFFER_ID }),
    orderAmounts: {} as Record<string, number>,
    submitting: {} as Record<string, boolean>,
    isReadOnly: false,
    onAmountChange: vi.fn(),
    onOrder: vi.fn(),
    onUpdate: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ── Branch 1: read-only ─────────────────────────────────────────────────────

describe("read-only branch", () => {
  it("renders the rounded ordered amount as a Tag when ordered > 0", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          isReadOnly: true,
          record: makeRow({ id: OFFER_ID, ordered_amount_num: 4.6 }),
        })}
      />,
    );
    // 4.6 rounds to 5; suffix is the t() key (no fallback supplied)
    expect(screen.getByText(/5\s*commissioning\.pu/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a dash when ordered_amount is null", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          isReadOnly: true,
          record: makeRow({ id: OFFER_ID, ordered_amount_num: null }),
        })}
      />,
    );
    expect(screen.getByText("-")).toBeInTheDocument();
  });

  it("renders a dash when ordered_amount is 0 (not > 0)", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          isReadOnly: true,
          record: makeRow({ id: OFFER_ID, ordered_amount_num: 0 }),
        })}
      />,
    );
    expect(screen.getByText("-")).toBeInTheDocument();
  });
});

// ── Branch 2: finalized + existing order ────────────────────────────────────

describe("finalized branch", () => {
  it("renders a green Tag with the rounded ordered amount; no inputs", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          record: makeRow({
            id: OFFER_ID,
            order_content_id: ORDER_CONTENT_ID,
            order_is_finalized: true,
            ordered_amount_num: 3.2,
          }),
        })}
      />,
    );
    expect(screen.getByText(/3\s*commissioning\.pu/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

// ── Branch 3: editable existing order (PATCH) ───────────────────────────────

describe("editable existing-order branch (PATCH)", () => {
  function existingOrderRecord() {
    return makeRow({
      id: OFFER_ID,
      order_content_id: ORDER_CONTENT_ID,
      order_is_finalized: false,
      ordered_amount_num: 4,
    });
  }

  it("seeds the input with the rounded existing ordered amount when no pending edit exists", () => {
    render(<OrderAmountCell {...makeProps({ record: existingOrderRecord() })} />);
    const input = screen.getByLabelText("customer.order_amount") as HTMLInputElement;
    expect(input.value).toBe("4");
  });

  it("prefers the pending value in orderAmounts over the seeded ordered amount", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          record: existingOrderRecord(),
          orderAmounts: { [OFFER_ID]: 9 },
        })}
      />,
    );
    const input = screen.getByLabelText("customer.order_amount") as HTMLInputElement;
    expect(input.value).toBe("9");
  });

  it("calls onAmountChange while typing and onUpdate on button click", async () => {
    const props = makeProps({ record: existingOrderRecord() });
    render(<OrderAmountCell {...props} />);

    const input = screen.getByLabelText("customer.order_amount") as HTMLInputElement;
    // The input is *controlled* by the parent: ``value={editAmount || ""}``.
    // In isolation the parent never re-renders in response to our spy, so
    // the seeded "4" stays in the DOM. Typing "7" therefore appends to "47"
    // and onChange fires with Number("47") = 47. What matters here is that
    // the wiring fires onAmountChange with the parsed number, not the exact
    // digit. The not-yet-ordered branch test below exercises the empty-input
    // path where appending isn't a concern.
    await userEvent.type(input, "7");
    expect(props.onAmountChange).toHaveBeenLastCalledWith(OFFER_ID, 47);

    await userEvent.click(
      screen.getByRole("button", { name: "customer.update" }),
    );
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
    expect(props.onUpdate).toHaveBeenCalledWith(props.record);
    expect(props.onOrder).not.toHaveBeenCalled();
  });

  it("submits via Enter key", async () => {
    const props = makeProps({ record: existingOrderRecord() });
    render(<OrderAmountCell {...props} />);

    const input = screen.getByLabelText("customer.order_amount");
    await userEvent.type(input, "{Enter}");
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
    expect(props.onOrder).not.toHaveBeenCalled();
  });

  it("shows loading state on the Update button when submitting[offerId]", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          record: existingOrderRecord(),
          submitting: { [OFFER_ID]: true },
        })}
      />,
    );
    const btn = screen.getByRole("button", { name: /customer\.update/ });
    // AntD adds .ant-btn-loading when loading is true
    expect(btn.className).toMatch(/ant-btn-loading/);
  });
});

// ── Branch 4: not-yet-ordered (POST) ────────────────────────────────────────

describe("not-yet-ordered branch (POST)", () => {
  function newOfferRecord() {
    return makeRow({ id: OFFER_ID });
  }

  it("renders an empty input + Add button when no order exists yet", () => {
    render(<OrderAmountCell {...makeProps({ record: newOfferRecord() })} />);
    const input = screen.getByLabelText("customer.order_amount") as HTMLInputElement;
    expect(input.value).toBe("");
    // The Add button uses the customer.add key
    expect(
      screen.getByRole("button", { name: /customer\.add/ }),
    ).toBeInTheDocument();
    // …and NO Update button
    expect(
      screen.queryByRole("button", { name: "customer.update" }),
    ).not.toBeInTheDocument();
  });

  it("calls onAmountChange while typing and onOrder on Add click", async () => {
    const props = makeProps({ record: newOfferRecord() });
    render(<OrderAmountCell {...props} />);

    const input = screen.getByLabelText("customer.order_amount");
    await userEvent.type(input, "3");
    expect(props.onAmountChange).toHaveBeenLastCalledWith(OFFER_ID, 3);

    await userEvent.click(screen.getByRole("button", { name: /customer\.add/ }));
    expect(props.onOrder).toHaveBeenCalledTimes(1);
    expect(props.onOrder).toHaveBeenCalledWith(props.record);
    expect(props.onUpdate).not.toHaveBeenCalled();
  });

  it("submits via Enter key", async () => {
    const props = makeProps({ record: newOfferRecord() });
    render(<OrderAmountCell {...props} />);

    const input = screen.getByLabelText("customer.order_amount");
    await userEvent.type(input, "{Enter}");
    expect(props.onOrder).toHaveBeenCalledTimes(1);
    expect(props.onUpdate).not.toHaveBeenCalled();
  });

  it("uses the pending orderAmounts value for the input", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          record: newOfferRecord(),
          orderAmounts: { [OFFER_ID]: 6 },
        })}
      />,
    );
    const input = screen.getByLabelText("customer.order_amount") as HTMLInputElement;
    expect(input.value).toBe("6");
  });

  it("shows loading state on the Add button when submitting[offerId]", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          record: newOfferRecord(),
          submitting: { [OFFER_ID]: true },
        })}
      />,
    );
    const btn = screen.getByRole("button", { name: /customer\.add/ });
    expect(btn.className).toMatch(/ant-btn-loading/);
  });
});

