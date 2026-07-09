/**
 * Tier-4 seam test for ``OrderAmountCell``.
 *
 * The order-amount column is a single edit surface driven by one header
 * toggle, so the cell itself is a pure display of the column mode:
 *   1. frozen (read-only week OR finalized order) → static Tag / "-"
 *   2. view mode                                  → static Tag / "-"
 *   3. edit mode                                  → Input (seeded), no buttons
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

function makeProps(
  overrides: Partial<Parameters<typeof OrderAmountCell>[0]> = {},
) {
  return {
    record: makeRow({ id: OFFER_ID }),
    orderAmounts: {} as Record<string, number>,
    editMode: false,
    saving: false,
    isReadOnly: false,
    onAmountChange: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides,
  };
}

function existingOrderRow() {
  return makeRow({
    id: OFFER_ID,
    order_content_id: ORDER_CONTENT_ID,
    order_is_finalized: false,
    ordered_amount_num: 4,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ── Branch 1: frozen (read-only / finalized) ────────────────────────────────

describe("frozen branch", () => {
  it("renders the rounded ordered amount as a Tag when read-only and ordered > 0", () => {
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

  it("renders a dash when read-only and ordered_amount is null", () => {
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

  it("renders a dash when read-only and ordered_amount is 0 (not > 0)", () => {
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

  it("stays frozen (green Tag, no input) for a finalized order even in edit mode", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          editMode: true,
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
  });
});

// ── Branch 2: view mode ─────────────────────────────────────────────────────

describe("view mode", () => {
  it("renders the placed amount as a Tag (no input) for an existing order", () => {
    render(<OrderAmountCell {...makeProps({ record: existingOrderRow() })} />);
    expect(screen.getByText(/4\s*commissioning\.pu/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("renders a dash for a not-yet-ordered offer", () => {
    render(
      <OrderAmountCell {...makeProps({ record: makeRow({ id: OFFER_ID }) })} />,
    );
    expect(screen.getByText("-")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

// ── Branch 3: edit mode ─────────────────────────────────────────────────────

describe("edit mode", () => {
  it("seeds the input with the rounded existing ordered amount when no pending edit exists", () => {
    render(
      <OrderAmountCell
        {...makeProps({ editMode: true, record: existingOrderRow() })}
      />,
    );
    const input = screen.getByLabelText(
      "customer.order_amount",
    ) as HTMLInputElement;
    expect(input.value).toBe("4");
  });

  it("renders an empty input for a not-yet-ordered offer", () => {
    render(
      <OrderAmountCell
        {...makeProps({ editMode: true, record: makeRow({ id: OFFER_ID }) })}
      />,
    );
    const input = screen.getByLabelText(
      "customer.order_amount",
    ) as HTMLInputElement;
    expect(input.value).toBe("");
  });

  it("prefers the pending value in orderAmounts over the seeded ordered amount", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          editMode: true,
          record: existingOrderRow(),
          orderAmounts: { [OFFER_ID]: 9 },
        })}
      />,
    );
    const input = screen.getByLabelText(
      "customer.order_amount",
    ) as HTMLInputElement;
    expect(input.value).toBe("9");
  });

  it("calls onAmountChange while typing", async () => {
    const props = makeProps({ editMode: true, record: makeRow({ id: OFFER_ID }) });
    render(<OrderAmountCell {...props} />);

    const input = screen.getByLabelText("customer.order_amount");
    await userEvent.type(input, "3");
    expect(props.onAmountChange).toHaveBeenLastCalledWith(OFFER_ID, 3);
  });

  it("calls onSubmit on Enter", async () => {
    const props = makeProps({ editMode: true, record: existingOrderRow() });
    render(<OrderAmountCell {...props} />);

    const input = screen.getByLabelText("customer.order_amount");
    await userEvent.type(input, "{Enter}");
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it("disables the input while saving", () => {
    render(
      <OrderAmountCell
        {...makeProps({
          editMode: true,
          saving: true,
          record: existingOrderRow(),
        })}
      />,
    );
    const input = screen.getByLabelText(
      "customer.order_amount",
    ) as HTMLInputElement;
    expect(input).toBeDisabled();
  });

  it("paints the input red + shows the ceiling tag when the row has a stock error", () => {
    const { container } = render(
      <OrderAmountCell
        {...makeProps({
          editMode: true,
          record: makeRow({ id: OFFER_ID }),
          // available is the VPE ceiling directly (floor(5) = 5)
          stockError: { available: 5, requested: 16 },
        })}
      />,
    );
    // AntD paints a status-error class somewhere on the input tree when
    // status="error" (exact class varies by variant/affix wrapper)
    expect(
      container.querySelector('[class*="status-error"]'),
    ).toBeInTheDocument();
    // The tiny ceiling tag renders (i18n mock returns the key; the mock
    // doesn't interpolate the count)
    expect(
      screen.getByText("customer.insufficient_stock_tag"),
    ).toBeInTheDocument();
  });

  it("shows no stock tag when the row has no stock error", () => {
    render(
      <OrderAmountCell
        {...makeProps({ editMode: true, record: existingOrderRow() })}
      />,
    );
    expect(
      screen.queryByText("customer.insufficient_stock_tag"),
    ).not.toBeInTheDocument();
  });
});
