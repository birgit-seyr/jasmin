/**
 * The table-style list documents: BaseListPDF (generic column-driven table),
 * HarvestingListPDF (BaseListPDF plus the first-page totals) and the
 * washing / cleaning worksheets (ArticleAmountTickListPDF).
 */
import { render, screen, within } from "@testing-library/react";
import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@react-pdf/renderer", async (importOriginal) => {
  const { pdfDomPrimitives } = await import(
    "@features/commissioning/pdfs/__tests__/pdfDomPrimitives"
  );
  return {
    ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
    ...pdfDomPrimitives(),
  };
});

import ArticleAmountTickListPDF, {
  cleanAmountAccessor,
  washAmountAccessor,
  type ArticleAmountTickItem,
} from "../ArticleAmountTickListPDF";
import BaseListPDF from "../BaseListPDF";
import CleaningListPDF from "../CleaningListPDF";
import HarvestingListPDF from "../HarvestingListPDF";
import WashingListPDF from "../WashingListPDF";

const LABELS: Record<string, string> = {
  "common.page": "Page",
  "common.of": "of",
  "commissioning.KW": "KW",
  "commissioning.washing_list": "Washing list",
  "commissioning.cleaning_list": "Cleaning list",
  "commissioning.vegetables_and_fruits": "Vegetables and fruits",
  "commissioning.amount": "Amount",
  "commissioning.note": "Note",
};
const t = ((key: string) => LABELS[key] ?? key) as unknown as TFunction;

const columns = [
  {
    key: "article",
    dataIndex: "article",
    pdf: { include: true, title: "Article", width: "60%" },
  },
  {
    key: "amount",
    dataIndex: "amount",
    pdf: { include: true, title: "Amount", width: "40%", align: "right" },
  },
  // Screen-only column: never printed.
  { key: "actions", dataIndex: "actions", title: "Actions" },
];

const rowsOf = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("[data-wrap='false']"));

describe("BaseListPDF", () => {
  it("prints the pill, title, subtitle, header and one unsplittable row per item", () => {
    const { container } = render(
      <BaseListPDF
        data={[
          { id: "1", article: "Carrots", amount: "12,5 kg" },
          { id: "2", article: "Leek", amount: "3 Bund" },
        ]}
        title="Harvest list"
        subtitle="KW 12 · Tuesday"
        pill="Harvest"
        columns={columns}
      />,
    );
    const page = container.querySelector("[data-pdf='page']")!;
    expect(page).toHaveAttribute("data-orientation", "portrait");
    expect(page).toHaveAttribute("data-size", "A4");
    expect(screen.getByText("Harvest")).toBeInTheDocument();
    expect(screen.getByText("Harvest list")).toBeInTheDocument();
    expect(screen.getByText("KW 12 · Tuesday")).toBeInTheDocument();

    const header = container.querySelector("[data-fixed='true']")!;
    expect(header.textContent).toBe("ArticleAmount");
    expect(screen.queryByText("Actions")).toBeNull();

    const rows = rowsOf(container);
    expect(rows.map((row) => row.textContent)).toEqual([
      "Carrots12,5 kg",
      "Leek3 Bund",
    ]);
    expect(screen.getByText("common.page 2 common.of 5")).toBeInTheDocument();
  });

  it("prints a dash for an empty cell", () => {
    const { container } = render(
      <BaseListPDF
        data={[{ article: "Carrots", amount: null }]}
        title="List"
        subtitle=""
        columns={columns}
      />,
    );
    expect(rowsOf(container)[0].textContent).toBe("Carrots—");
  });

  it("leaves out the subtitle, pill and table when there is nothing to print", () => {
    const { container } = render(
      <BaseListPDF data={[]} title="List" subtitle="" columns={columns} />,
    );
    expect(screen.queryByText("Article")).toBeNull();
    expect(rowsOf(container)).toHaveLength(0);
    // Title + page footer only.
    expect(container.querySelectorAll("[data-pdf='text']")).toHaveLength(2);
  });

  it("puts the first-page content between header and table, in landscape when asked", () => {
    const { container } = render(
      <BaseListPDF
        data={[{ id: "1", article: "Carrots", amount: "1" }]}
        title="List"
        subtitle=""
        columns={columns}
        firstPageContent={<span>Totals card</span>}
        orientation="landscape"
      />,
    );
    expect(container.querySelector("[data-pdf='page']")).toHaveAttribute(
      "data-orientation",
      "landscape",
    );
    expect(container.textContent!.indexOf("Totals card")).toBeLessThan(
      container.textContent!.indexOf("Article"),
    );
  });
});

describe("HarvestingListPDF", () => {
  it("prints the variation totals and the crate counts on the first page, in landscape", () => {
    const { container } = render(
      <HarvestingListPDF
        data={[{ id: "1", article: "Carrots", amount: "40 kg" }]}
        dataFirstPageOnly={[
          { crate_name: "Euro crate", quantity: 4 },
          { crate_name: "Small crate", quantity: 0 },
        ]}
        variationsTotals={[{ id: 1, size: "M", totalQuantity: 30 }]}
        title="Harvest list"
        subtitle="KW 12"
        columns={columns}
      />,
    );
    expect(container.querySelector("[data-pdf='page']")).toHaveAttribute(
      "data-orientation",
      "landscape",
    );
    expect(screen.getByText("commissioning.variations_totals")).toBeInTheDocument();
    expect(screen.getByText("commissioning.M:")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("commissioning.harvesting_crate")).toBeInTheDocument();
    expect(screen.getByText("commissioning.quantity")).toBeInTheDocument();
    const euro = screen.getByText("Euro crate").closest("[data-pdf='view']")!
      .parentElement!;
    expect(within(euro).getByText("4")).toBeInTheDocument();
    const small = screen.getByText("Small crate").closest("[data-pdf='view']")!
      .parentElement!;
    expect(within(small).getByText("0")).toBeInTheDocument();
    expect(rowsOf(container).map((row) => row.textContent)).toEqual([
      "Carrots40 kg",
    ]);
  });

  it("leaves out both first-page cards when there are no totals or crates", () => {
    render(
      <HarvestingListPDF
        data={[{ id: "1", article: "Carrots", amount: "40 kg" }]}
        title="Harvest list"
        subtitle=""
        columns={columns}
      />,
    );
    expect(screen.queryByText("commissioning.variations_totals")).toBeNull();
    expect(screen.queryByText("commissioning.harvesting_crate")).toBeNull();
    expect(screen.getByText("Carrots")).toBeInTheDocument();
  });
});

const items: ArticleAmountTickItem[] = [
  {
    id: 1,
    computed_article_with_size: "Carrots (large)",
    computed_total_wash_amount_text: "12,5 kg",
    computed_total_clean_amount_text: "10 kg",
    note: "Remove the leaves",
  },
  {
    id: 2,
    computed_article_with_size: "Leek",
    computed_total_wash_amount_text: "3 Bund",
  },
];

describe("ArticleAmountTickListPDF", () => {
  it("prints the pill, week and day, and the header that repeats on every page", () => {
    const { container } = render(
      <ArticleAmountTickListPDF
        data={items}
        year={2026}
        week={12}
        dayName="Tuesday"
        pillKey="commissioning.washing_list"
        amountAccessor={washAmountAccessor}
        t={t}
      />,
    );
    expect(screen.getByText("Washing list")).toBeInTheDocument();
    expect(screen.getByText("KW 12 · Tuesday")).toBeInTheDocument();
    const header = container.querySelector("[data-fixed='true']")!;
    expect(header.textContent).toBe("Vegetables and fruitsAmountNote✓");
    expect(screen.getByText("Page 2 of 5")).toBeInTheDocument();
  });

  it("prints a row per article with its amount, its note and an empty tick box", () => {
    const { container } = render(
      <ArticleAmountTickListPDF
        data={items}
        year={2026}
        week={12}
        dayName="Tuesday"
        pillKey="commissioning.washing_list"
        amountAccessor={washAmountAccessor}
        t={t}
      />,
    );
    const rows = rowsOf(container);
    expect(rows.map((row) => row.textContent)).toEqual([
      "Carrots (large)12,5 kgRemove the leaves",
      "Leek3 Bund",
    ]);
  });

  it("prints blank cells for a row without article, amount or note", () => {
    const { container } = render(
      <ArticleAmountTickListPDF
        data={[{}]}
        year={2026}
        week={12}
        dayName="Tuesday"
        pillKey="commissioning.cleaning_list"
        amountAccessor={cleanAmountAccessor}
        t={t}
      />,
    );
    expect(rowsOf(container)).toHaveLength(1);
    expect(rowsOf(container)[0].textContent).toBe("");
  });

  it("prints just the header for an empty list", () => {
    const { container } = render(
      <ArticleAmountTickListPDF
        data={[]}
        year={2026}
        week={12}
        dayName="Tuesday"
        pillKey="commissioning.washing_list"
        amountAccessor={washAmountAccessor}
        t={t}
      />,
    );
    expect(rowsOf(container)).toHaveLength(0);
    expect(screen.getByText("Vegetables and fruits")).toBeInTheDocument();
  });
});

describe("accessors", () => {
  it("read the wash and the clean amount text", () => {
    expect(washAmountAccessor(items[0])).toBe("12,5 kg");
    expect(cleanAmountAccessor(items[0])).toBe("10 kg");
    expect(cleanAmountAccessor(items[1])).toBeUndefined();
  });
});

describe("WashingListPDF / CleaningListPDF", () => {
  it("the washing list prints the wash amounts under its own pill", () => {
    const { container } = render(
      <WashingListPDF
        data={items}
        year={2026}
        week={12}
        dayName="Tuesday"
        t={t}
      />,
    );
    expect(screen.getByText("Washing list")).toBeInTheDocument();
    expect(rowsOf(container)[0].textContent).toContain("12,5 kg");
  });

  it("the cleaning list prints the clean amounts under its own pill", () => {
    const { container } = render(
      <CleaningListPDF
        data={items}
        year={2026}
        week={12}
        dayName="Friday"
        t={t}
      />,
    );
    expect(screen.getByText("Cleaning list")).toBeInTheDocument();
    expect(screen.getByText("KW 12 · Friday")).toBeInTheDocument();
    expect(rowsOf(container).map((row) => row.textContent)).toEqual([
      "Carrots (large)10 kgRemove the leaves",
      "Leek",
    ]);
  });
});
