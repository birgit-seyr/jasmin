/**
 * Tier-4 seam test for ``CustomerDocumentsCard``.
 *
 * The card has three things worth pinning:
 *   1. it scans ``orderContents`` for the FIRST item with each id field
 *      and uses that to drive the two query hooks
 *   2. it gates each query via React Query's ``enabled`` — the query
 *      only fires when id is present AND the corresponding "finalized"
 *      flag is true somewhere in the rows
 *   3. each button is disabled until the query returns a file URL, and
 *      clicking opens the URL in a new tab
 *
 * Boundary mock: the two generated retrieve hooks.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

type RetrieveOpts = { query?: { enabled?: boolean } };
type RetrieveResult = { data?: { file?: string } | undefined };

const dnRetrieveMock = vi.fn<(id: string, opts: RetrieveOpts) => RetrieveResult>();
const invRetrieveMock = vi.fn<(id: string, opts: RetrieveOpts) => RetrieveResult>();

vi.mock("@shared/api/generated/commissioning/commissioning", () => ({
  useCommissioningDeliveryNotesRetrieve: (id: string, opts: RetrieveOpts) =>
    dnRetrieveMock(id, opts),
  useCommissioningInvoicesRetrieve: (id: string, opts: RetrieveOpts) =>
    invRetrieveMock(id, opts),
}));

import CustomerDocumentsCard from "../CustomerDocumentsCard";
import type { OrderContentListItem } from "@shared/api/generated/models";

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Fixture helper: the card only reads the document-reference fields. */
const makeItem = (item: Partial<OrderContentListItem>) =>
  item as OrderContentListItem;

const originalOpen = window.open;
let windowOpenSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  dnRetrieveMock.mockReset().mockReturnValue({ data: undefined });
  invRetrieveMock.mockReset().mockReturnValue({ data: undefined });
  windowOpenSpy = vi.fn();
  window.open = windowOpenSpy as unknown as typeof window.open;
});

afterEach(() => {
  window.open = originalOpen;
});

// Source uses regex-y i18n keys: t("customer.delivery_note") and
// t("customer.invoice"). With the canonical mock (no fallback supplied)
// these return the key verbatim — so we match on the key as button name.
const DN_BUTTON = /customer\.delivery_note/;
const INV_BUTTON = /customer\.invoice/;

// ── Empty input ─────────────────────────────────────────────────────────────

describe("with no order contents", () => {
  it("calls all query hooks with enabled:false and disables both buttons", () => {
    render(<CustomerDocumentsCard orderContents={[]} />);

    expect(dnRetrieveMock).toHaveBeenCalledTimes(1);
    // invoice retrieve + storno retrieve both route through this hook.
    expect(invRetrieveMock).toHaveBeenCalledTimes(2);
    // enabled must be false because no id was discovered (invoice → call 0,
    // storno → call 1, gated off because the invoice isn't cancelled).
    expect(dnRetrieveMock.mock.calls[0][1].query?.enabled).toBe(false);
    expect(invRetrieveMock.mock.calls[0][1].query?.enabled).toBe(false);
    expect(invRetrieveMock.mock.calls[1][1].query?.enabled).toBe(false);

    expect(screen.getByRole("button", { name: DN_BUTTON })).toBeDisabled();
    expect(screen.getByRole("button", { name: INV_BUTTON })).toBeDisabled();
  });
});

// ── Delivery note ───────────────────────────────────────────────────────────

describe("delivery note", () => {
  const baseRow = {
    delivery_note_id: "dn-123",
    delivery_note_prefix: "LS",
    delivery_note_number: "2026-001",
  };

  it("does NOT enable the query when no row is finalized", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, delivery_note_is_finalized: false })]}
      />,
    );
    expect(dnRetrieveMock.mock.calls[0][1].query?.enabled).toBe(false);
    expect(screen.getByRole("button", { name: DN_BUTTON })).toBeDisabled();
  });

  it("enables the query when at least one row is finalized; button disabled until file lands", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, delivery_note_is_finalized: true })]}
      />,
    );
    // enabled flips true once id + finalized are both satisfied.
    expect(dnRetrieveMock.mock.calls[0][0]).toBe("dn-123");
    expect(dnRetrieveMock.mock.calls[0][1].query?.enabled).toBe(true);
    // No file yet → still disabled.
    expect(screen.getByRole("button", { name: DN_BUTTON })).toBeDisabled();
  });

  it("enables the button and opens the file in a new tab when the query resolves", async () => {
    dnRetrieveMock.mockReturnValue({
      data: { file: "https://files.test/dn-123.pdf" },
    });

    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, delivery_note_is_finalized: true })]}
      />,
    );

    const btn = screen.getByRole("button", { name: DN_BUTTON });
    expect(btn).not.toBeDisabled();
    await userEvent.click(btn);
    expect(windowOpenSpy).toHaveBeenCalledWith(
      "https://files.test/dn-123.pdf",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("renders the #PREFIX+NUMBER label whenever a delivery_note_id exists", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, delivery_note_is_finalized: false })]}
      />,
    );
    // Number label is independent of the finalized/enabled flag.
    expect(screen.getByText("#LS2026-001")).toBeInTheDocument();
  });
});

// ── Invoice ─────────────────────────────────────────────────────────────────

describe("invoice", () => {
  const baseRow = {
    invoice_id: "inv-555",
    invoice_prefix: "RE",
    invoice_number: "2026-042",
  };

  it("does NOT enable the query when no row is finalized", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, has_finalized_invoice: false })]}
      />,
    );
    expect(invRetrieveMock.mock.calls[0][1].query?.enabled).toBe(false);
    expect(screen.getByRole("button", { name: INV_BUTTON })).toBeDisabled();
  });

  it("enables the query when at least one row is finalized", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, has_finalized_invoice: true })]}
      />,
    );
    expect(invRetrieveMock.mock.calls[0][0]).toBe("inv-555");
    expect(invRetrieveMock.mock.calls[0][1].query?.enabled).toBe(true);
  });

  it("opens the invoice file in a new tab when click and file present", async () => {
    invRetrieveMock.mockReturnValue({
      data: { file: "https://files.test/inv-555.pdf" },
    });

    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, has_finalized_invoice: true })]}
      />,
    );

    const btn = screen.getByRole("button", { name: INV_BUTTON });
    expect(btn).not.toBeDisabled();
    await userEvent.click(btn);
    expect(windowOpenSpy).toHaveBeenCalledWith(
      "https://files.test/inv-555.pdf",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("renders the #PREFIX+NUMBER label whenever an invoice_id exists", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[makeItem({ ...baseRow, has_finalized_invoice: false })]}
      />,
    );
    expect(screen.getByText("#RE2026-042")).toBeInTheDocument();
  });
});

// ── Cross-row discovery ─────────────────────────────────────────────────────

describe("first-match discovery across rows", () => {
  it("uses the first row's delivery_note_id and the first row's invoice_id, even if they're on different rows", () => {
    render(
      <CustomerDocumentsCard
        orderContents={[
          // Row with only the delivery note ref
          makeItem({
            delivery_note_id: "dn-A",
            delivery_note_prefix: "LS",
            delivery_note_number: "1",
            delivery_note_is_finalized: true,
          }),
          // Row with only the invoice ref
          makeItem({
            invoice_id: "inv-B",
            invoice_prefix: "RE",
            invoice_number: "2",
            has_finalized_invoice: true,
          }),
        ]}
      />,
    );

    expect(dnRetrieveMock.mock.calls[0][0]).toBe("dn-A");
    expect(invRetrieveMock.mock.calls[0][0]).toBe("inv-B");
    expect(dnRetrieveMock.mock.calls[0][1].query?.enabled).toBe(true);
    expect(invRetrieveMock.mock.calls[0][1].query?.enabled).toBe(true);

    expect(screen.getByText("#LS1")).toBeInTheDocument();
    expect(screen.getByText("#RE2")).toBeInTheDocument();
  });
});
