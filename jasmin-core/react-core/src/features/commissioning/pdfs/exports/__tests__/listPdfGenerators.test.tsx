/**
 * The list-PDF download buttons: each wrapper loads its own document on click
 * and hands it the props it needs, under the file name it was given.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TFunction } from "i18next";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

const { rendered, downloadBlobMock, notifyMock } = vi.hoisted(() => ({
  rendered: { element: null as ReactElement | null },
  downloadBlobMock: vi.fn(),
  notifyMock: { error: vi.fn() },
}));

vi.mock("@react-pdf/renderer", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
  pdf: (element: ReactElement) => {
    rendered.element = element;
    return { toBlob: async () => new Blob(["%PDF"]) };
  },
}));

vi.mock("@shared/utils", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@shared/utils")>()),
  downloadBlob: downloadBlobMock,
  notify: notifyMock,
}));

import ArticleAmountTickListPDF, {
  cleanAmountAccessor,
  washAmountAccessor,
} from "../ArticleAmountTickListPDF";
import ArticleAmountTickListPDFGenerator from "../ArticleAmountTickListPDFGenerator";
import CleaningListPDFGenerator from "../CleaningListPDFGenerator";
import HarvestingListPDF from "../HarvestingListPDF";
import HarvestingListPDFGenerator from "../HarvestingListPDFGenerator";
import WashingListPDFGenerator from "../WashingListPDFGenerator";

const t = ((key: string) => key) as unknown as TFunction;

const items = [
  {
    id: 1,
    computed_article_with_size: "Carrots",
    computed_total_wash_amount_text: "4 kg",
  },
];

beforeEach(() => {
  rendered.element = null;
  downloadBlobMock.mockReset();
  notifyMock.error.mockReset();
});

async function clickDownload() {
  await userEvent.click(screen.getByRole("button", { name: /Download/ }));
  await waitFor(() => expect(downloadBlobMock).toHaveBeenCalled());
}

describe("ArticleAmountTickListPDFGenerator", () => {
  it("renders the tick list with the chosen variant and downloads it under the file name", async () => {
    render(
      <ArticleAmountTickListPDFGenerator
        data={items}
        year={2026}
        week={12}
        dayName="Tuesday"
        filename="washing-list-kw12"
        buttonText="Download"
        pillKey="commissioning.washing_list"
        amountAccessor={washAmountAccessor}
        t={t}
      />,
    );
    await clickDownload();

    expect(rendered.element!.type).toBe(ArticleAmountTickListPDF);
    expect(rendered.element!.props).toMatchObject({
      data: items,
      year: 2026,
      week: 12,
      dayName: "Tuesday",
      pillKey: "commissioning.washing_list",
      amountAccessor: washAmountAccessor,
    });
    expect(downloadBlobMock.mock.calls[0][1]).toBe("washing-list-kw12.pdf");
    expect(notifyMock.error).not.toHaveBeenCalled();
  });

  it("keeps the button disabled without data", () => {
    render(
      <ArticleAmountTickListPDFGenerator
        data={null}
        year={2026}
        week={12}
        dayName="Tuesday"
        filename="list"
        buttonText="Download"
        pillKey="commissioning.washing_list"
        amountAccessor={washAmountAccessor}
        t={t}
      />,
    );
    expect(screen.getByRole("button", { name: /Download/ })).toBeDisabled();
  });

  it("keeps the button disabled for an empty list", () => {
    render(
      <ArticleAmountTickListPDFGenerator
        data={[]}
        year={2026}
        week={12}
        dayName="Tuesday"
        filename="list"
        buttonText="Download"
        pillKey="commissioning.washing_list"
        amountAccessor={washAmountAccessor}
        t={t}
      />,
    );
    expect(screen.getByRole("button", { name: /Download/ })).toBeDisabled();
  });
});

describe("WashingListPDFGenerator / CleaningListPDFGenerator", () => {
  it("the washing button prints the wash amounts under the washing pill", async () => {
    render(
      <WashingListPDFGenerator
        data={items}
        year={2026}
        week={12}
        dayName="Tuesday"
        filename="washing"
        buttonText="Download"
        t={t}
      />,
    );
    await clickDownload();
    expect(rendered.element!.props).toMatchObject({
      pillKey: "commissioning.washing_list",
      amountAccessor: washAmountAccessor,
    });
    expect(downloadBlobMock.mock.calls[0][1]).toBe("washing.pdf");
  });

  it("the cleaning button prints the clean amounts under the cleaning pill", async () => {
    render(
      <CleaningListPDFGenerator
        data={items}
        year={2026}
        week={12}
        dayName="Tuesday"
        filename="cleaning"
        buttonText="Download"
        t={t}
      />,
    );
    await clickDownload();
    expect(rendered.element!.props).toMatchObject({
      pillKey: "commissioning.cleaning_list",
      amountAccessor: cleanAmountAccessor,
    });
    expect(downloadBlobMock.mock.calls[0][1]).toBe("cleaning.pdf");
  });
});

describe("HarvestingListPDFGenerator", () => {
  const columns = [{ key: "a", pdf: { include: true, title: "A" } }];

  it("renders the harvesting list with its first-page totals", async () => {
    const crates = [{ crate_name: "Euro crate", quantity: 3 }];
    const totals = [{ id: 1, size: "M", totalQuantity: 20 }];
    render(
      <HarvestingListPDFGenerator
        data={[{ id: "1", a: "Carrots" }]}
        dataFirstPageOnly={crates}
        variationsTotals={totals}
        title="Harvest list"
        subtitle="KW 12"
        pill="Harvest"
        columns={columns}
        filename="harvest-kw12"
        buttonText="Download"
      />,
    );
    await clickDownload();
    expect(rendered.element!.type).toBe(HarvestingListPDF);
    expect(rendered.element!.props).toMatchObject({
      data: [{ id: "1", a: "Carrots" }],
      dataFirstPageOnly: crates,
      variationsTotals: totals,
      title: "Harvest list",
      subtitle: "KW 12",
      pill: "Harvest",
      columns,
    });
    expect(downloadBlobMock.mock.calls[0][1]).toBe("harvest-kw12.pdf");
  });

  it("passes no crate summary when there is none", async () => {
    render(
      <HarvestingListPDFGenerator
        data={[{ id: "1", a: "Carrots" }]}
        dataFirstPageOnly={null}
        title="Harvest list"
        subtitle=""
        columns={columns}
        filename="harvest"
        buttonText="Download"
      />,
    );
    await clickDownload();
    expect(
      (rendered.element!.props as { dataFirstPageOnly?: unknown })
        .dataFirstPageOnly,
    ).toBeUndefined();
  });

  it("keeps the button disabled without data", () => {
    render(
      <HarvestingListPDFGenerator
        data={null}
        title="Harvest list"
        subtitle=""
        columns={columns}
        filename="harvest"
        buttonText="Download"
      />,
    );
    expect(screen.getByRole("button", { name: /Download/ })).toBeDisabled();
  });
});
