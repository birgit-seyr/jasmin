/**
 * The harvesting list's phone card: the article, its bed and plot, what the
 * shares and the orders need and their sum, and the button that confirms the
 * harvest. The amounts arrive as text the list has already formatted, so the
 * card only shows them.
 */
import { render, screen, within } from "@testing-library/react";
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

import { HarvestingMobileCard } from "../HarvestingMobileCard";

const CONFIRM = "commissioning.actual_harvest";
const SHARES = "commissioning.title_share_content:";
const ORDERS = "commissioning.title_order_content:";

/** A row as the harvesting list computes it, with shares and orders. */
function harvestRow(overrides: Partial<TableRecord> = {}): TableRecord {
  return {
    key: "h-carrots",
    id: "h-carrots",
    share_article_name: "Carrots",
    size: "M",
    forecast_plot_name: "North field",
    forecast_bed_number: 7,
    computed_amount_per_pu_text: "1 PU = 10 kg",
    computed_total_amount_text_share_content: "12,50 kg",
    computed_amount_pu_text_share_content: "1,25 PU",
    computed_total_amount_text_order_content: "7,50 kg",
    computed_amount_pu_text_order_content: "0,75 PU",
    computed_total_amount_text: "20,00 kg",
    computed_amount_pu_text: "2,00 PU",
    computed_note_line: "Wash before packing",
    ...overrides,
  };
}

const handlers = {
  onEdit: vi.fn(),
  onConfirmHarvest: vi.fn(),
};

beforeEach(() => {
  handlers.onEdit.mockReset();
  handlers.onConfirmHarvest.mockReset();
});

interface CardOptions {
  record?: TableRecord;
  showPlotHeader?: boolean;
  isConfirmed?: boolean;
  isPast?: boolean;
  editable?: boolean;
}

function renderCard({
  record = harvestRow(),
  showPlotHeader = true,
  isConfirmed = false,
  isPast = false,
  editable = true,
}: CardOptions = {}) {
  return render(
    <HarvestingMobileCard
      record={record}
      onEdit={editable ? handlers.onEdit : undefined}
      onConfirmHarvest={handlers.onConfirmHarvest}
      showPlotHeader={showPlotHeader}
      isConfirmed={isConfirmed}
      isPast={isPast}
    />,
  );
}

/** The amounts table's rows as [label, unit amount, PU amount]. */
function amountRows(): string[][] {
  return Array.from(document.querySelectorAll(".harvest-amounts-table tr")).map((row) =>
    Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent ?? ""),
  );
}

const card = () => document.querySelector<HTMLElement>(".mobile-card-item")!;

/** The round confirm button, found by the tooltip title it shows. */
const confirmButton = () => screen.getByTitle(CONFIRM).closest("button")!;

describe("HarvestingMobileCard contents", () => {
  it("shows the article, bed, per-PU hint, note and the plot header", () => {
    renderCard();

    expect(screen.getByText("North field")).toHaveClass("harvest-plot-header");
    expect(screen.getByText("Carrots")).toBeInTheDocument();
    expect(screen.getByText("commissioning.bed_number: 7")).toBeInTheDocument();
    expect(screen.getByText("1 PU = 10 kg")).toBeInTheDocument();
    expect(screen.getByText("Wash before packing")).toBeInTheDocument();
  });

  it("lists what the shares and the orders need and their sum, in that order", () => {
    renderCard();

    expect(amountRows()).toEqual([
      [SHARES, "12,50 kg", "1,25 PU"],
      [ORDERS, "7,50 kg", "0,75 PU"],
      ["Σ", "20,00 kg", "2,00 PU"],
    ]);
    const rows = document.querySelectorAll(".harvest-amounts-table tr");
    expect(rows[0]).toHaveClass("text-share-content");
    expect(rows[1]).toHaveClass("text-order-content");
    expect(rows[2]).toHaveClass("is-bold", "has-border-top");
  });

  it("leaves out the orders line when nothing is ordered", () => {
    renderCard({
      record: harvestRow({
        computed_total_amount_text_order_content: "",
        computed_amount_pu_text_order_content: null,
      }),
    });

    expect(amountRows()).toEqual([
      [SHARES, "12,50 kg", "1,25 PU"],
      ["Σ", "20,00 kg", "2,00 PU"],
    ]);
  });

  it("keeps a line that has only a PU amount", () => {
    renderCard({
      record: harvestRow({
        computed_total_amount_text_share_content: "",
        computed_total_amount_text_order_content: "",
        computed_amount_pu_text_order_content: "",
        computed_total_amount_text: "",
      }),
    });

    expect(amountRows()).toEqual([
      [SHARES, "", "1,25 PU"],
      ["Σ", "", "2,00 PU"],
    ]);
  });

  it("shows no amounts table, hint or note for a row without them", () => {
    renderCard({
      record: {
        key: "h-beans",
        id: "h-beans",
        share_article_name: "Beans",
        forecast_bed_number: null,
      },
    });

    expect(screen.getByText("Beans")).toBeInTheDocument();
    expect(document.querySelector(".harvest-amounts-table")).toBeNull();
    expect(document.querySelector(".harvest-per-pu-hint")).toBeNull();
    expect(document.querySelector(".text-meta")).toBeNull();
    expect(screen.queryByText(/commissioning\.bed_number/)).not.toBeInTheDocument();
  });

  it("shows bed number zero", () => {
    renderCard({ record: harvestRow({ forecast_bed_number: 0 }) });

    expect(screen.getByText("commissioning.bed_number: 0")).toBeInTheDocument();
  });

  it("shows the plot header only on the card that starts a plot, and only with a plot name", () => {
    const { unmount } = renderCard({ showPlotHeader: false });
    expect(screen.queryByText("North field")).not.toBeInTheDocument();
    unmount();

    renderCard({ record: harvestRow({ forecast_plot_name: null }) });
    expect(document.querySelector(".harvest-plot-header")).toBeNull();
  });

  it.each([
    ["S", "commissioning.small"],
    ["L", "commissioning.large"],
  ])("labels size %s after the article name", (size, label) => {
    renderCard({ record: harvestRow({ size }) });

    expect(within(card()).getByText(label)).toHaveClass("text-hint");
  });

  it("shows no size label for the default size M", () => {
    renderCard();

    expect(screen.queryByText("commissioning.medium")).not.toBeInTheDocument();
  });
});

describe("HarvestingMobileCard actions", () => {
  it("opens the row's edit dialog on a tap or Enter on the card", async () => {
    const user = userEvent.setup();
    const record = harvestRow();
    renderCard({ record });

    await user.click(screen.getByText("Carrots"));
    expect(handlers.onEdit).toHaveBeenCalledTimes(1);
    expect(handlers.onEdit).toHaveBeenCalledWith(record);

    card().focus();
    await user.keyboard("{Enter}");
    expect(handlers.onEdit).toHaveBeenCalledTimes(2);
    expect(handlers.onConfirmHarvest).not.toHaveBeenCalled();
  });

  it("is not a button when the row can't be edited", async () => {
    const user = userEvent.setup();
    renderCard({ editable: false });

    expect(card()).not.toHaveAttribute("role");
    expect(card()).not.toHaveAttribute("tabindex");
    await user.click(screen.getByText("Carrots"));
    expect(handlers.onEdit).not.toHaveBeenCalled();
  });

  it("confirms the harvest without also opening the edit dialog", async () => {
    const user = userEvent.setup();
    const record = harvestRow();
    renderCard({ record });

    await user.click(confirmButton());

    expect(handlers.onConfirmHarvest).toHaveBeenCalledTimes(1);
    expect(handlers.onConfirmHarvest).toHaveBeenCalledWith(record);
    expect(handlers.onEdit).not.toHaveBeenCalled();
  });

  it("confirms the harvest from the keyboard without opening the edit dialog", async () => {
    const user = userEvent.setup();
    renderCard();

    confirmButton().focus();
    await user.keyboard("{Enter}");

    expect(handlers.onConfirmHarvest).toHaveBeenCalledTimes(1);
    expect(handlers.onEdit).not.toHaveBeenCalled();
  });

  // HarvestingMobileCard.css colours the button green through `is-confirmed`
  // and red without it; jsdom loads no stylesheet, so the class is the contract.
  it("marks the confirm button confirmed once confirmed and not before", () => {
    const { unmount } = renderCard({ isConfirmed: true });
    expect(confirmButton()).toHaveClass("harvest-confirm-button", "is-confirmed");
    expect(confirmButton()).not.toHaveAttribute("style");
    unmount();

    renderCard({ isConfirmed: false });
    expect(confirmButton()).toHaveClass("harvest-confirm-button");
    expect(confirmButton()).not.toHaveClass("is-confirmed");
  });

  it.skip("names the confirm button for screen readers by what it does", () => {
    renderCard();

    expect(screen.getByRole("button", { name: CONFIRM })).toBe(confirmButton());
  });

  it("offers no confirmation for a past day", () => {
    renderCard({ isPast: true });

    expect(screen.queryByTitle(CONFIRM)).not.toBeInTheDocument();
    expect(screen.getByText("Carrots")).toBeInTheDocument();
  });
});
