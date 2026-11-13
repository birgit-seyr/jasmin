/**
 * @vitest-environment node
 *
 * Lays the list documents out with the real react-pdf engine (Node's Blob has
 * ``arrayBuffer()``, jsdom's does not): a long list must flow onto more pages
 * rather than fail or get cut off, and every document must come out as a PDF.
 */
import { Document, Page, pdf } from "@react-pdf/renderer";
import type { TFunction } from "i18next";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

// boxComboPdf reads its size labels through the hooks barrel, which loads the
// app's i18n setup; that touches ``document`` and has no place in Node.
vi.mock("@shared/i18n", () => ({
  default: { t: (key: string) => key, language: "de", on: () => {} },
}));

import "../../registerRoboto";
import BaseListPDF from "../BaseListPDF";
import CleaningListPDF from "../CleaningListPDF";
import HarvestingListPDF from "../HarvestingListPDF";
import MarketMemberListPDF from "../MarketMemberListPDF";
import MarketOrderListPDF from "../MarketOrderListPDF";
import MarketPriceListPDF from "../MarketPriceListPDF";
import WashingListPDF from "../WashingListPDF";
import {
  ComboColumnHeaderRow,
  ComboGroupHeaderRow,
  computeGroupEdges,
  groupComboColumns,
} from "../boxComboPdf";
import { ListPDFHeader } from "../ListPDFSharedComponents";

const t = ((key: string) => key) as unknown as TFunction;

async function layout(document: ReactElement) {
  const blob = await pdf(document).toBlob();
  const text = Buffer.from(await blob.arrayBuffer()).toString("latin1");
  return {
    isPdf: text.startsWith("%PDF-"),
    pages: (text.match(/\/Type \/Page\b/g) ?? []).length,
  };
}

const washItems = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    id: index,
    computed_article_with_size: `Article ${index}`,
    computed_total_wash_amount_text: `${index},5 kg`,
    computed_total_clean_amount_text: `${index} kg`,
    note: index % 3 === 0 ? "A longer note that has to wrap ".repeat(4) : "",
  }));

// A farm's market range: 384 PLUs in 17 product groups.
const marketGroups = Array.from({ length: 17 }, (_, group) => ({
  label: `${group + 1} Group ${group + 1}`,
  rows: Array.from({ length: group < 10 ? 23 : 22 }, (_, index) => {
    const plu = group * 100 + index;
    return { id: String(plu), plu_number: plu, name: `Organic produce ${plu} DE/FR` };
  }),
}));

const columns = [
  { key: "article", dataIndex: "article", pdf: { include: true, title: "Article", width: "60%" } },
  { key: "amount", dataIndex: "amount", pdf: { include: true, title: "Amount", width: "40%" } },
];

describe("list PDF layout", () => {
  it("lays a short washing list out on one page", async () => {
    const result = await layout(
      <WashingListPDF data={washItems(3)} year={2026} week={12} dayName="Tue" t={t} />,
    );
    expect(result).toEqual({ isPdf: true, pages: 1 });
  }, 30_000);

  it("flows a long cleaning list onto further pages", async () => {
    const result = await layout(
      <CleaningListPDF data={washItems(120)} year={2026} week={12} dayName="Tue" t={t} />,
    );
    expect(result.isPdf).toBe(true);
    expect(result.pages).toBeGreaterThan(2);
  }, 30_000);

  it("lays an empty base list out as one page", async () => {
    const result = await layout(
      <BaseListPDF data={[]} title="List" subtitle="" columns={columns} />,
    );
    expect(result).toEqual({ isPdf: true, pages: 1 });
  }, 30_000);

  it("flows a long harvesting list with its first-page totals onto further pages", async () => {
    const result = await layout(
      <HarvestingListPDF
        data={Array.from({ length: 80 }, (_, index) => ({
          id: String(index),
          article: `Article ${index}`,
          amount: `${index} kg`,
        }))}
        dataFirstPageOnly={[{ crate_name: "Euro crate", quantity: 4 }]}
        variationsTotals={[{ id: 1, size: "M", totalQuantity: 30 }]}
        title="Harvest"
        subtitle="KW 12"
        pill="Harvest"
        columns={columns}
      />,
    );
    expect(result.isPdf).toBe(true);
    expect(result.pages).toBeGreaterThan(1);
  }, 30_000);

  it("keeps a market price list of 384 PLUs in 17 groups to 9 pages", async () => {
    const result = await layout(
      <MarketPriceListPDF
        year={2026}
        week={47}
        t={t}
        groups={marketGroups.map((group) => ({
          label: group.label,
          rows: group.rows.map((row) => ({
            ...row,
            price_text: "12,90 €/kg",
            is_changed: row.plu_number % 9 === 0,
          })),
        }))}
      />,
    );
    expect(result.isPdf).toBe(true);
    expect(result.pages).toBeLessThanOrEqual(9);
  }, 30_000);

  it("keeps the order list of the same PLUs, with room to write, to 10 pages", async () => {
    const result = await layout(
      <MarketOrderListPDF
        year={2026}
        week={47}
        t={t}
        groups={marketGroups.map((group) => ({
          label: group.label,
          rows: group.rows.map((row) => ({ ...row, unit_label: "kg", price_text: "12,90 €" })),
        }))}
      />,
    );
    expect(result.isPdf).toBe(true);
    expect(result.pages).toBeLessThanOrEqual(10);
  }, 30_000);

  it("keeps a member list of 300 members to 7 pages", async () => {
    const result = await layout(
      <MarketMemberListPDF
        asOf="12.11.2026"
        t={t}
        members={Array.from({ length: 300 }, (_, index) => ({
          id: String(index),
          last_name: `Schwarzwälder-Müller ${index}`,
          first_name: "Maximilian",
          member_number: index + 1,
        }))}
      />,
    );
    expect(result.isPdf).toBe(true);
    expect(result.pages).toBeLessThanOrEqual(7);
  }, 30_000);

  it("lays the combination header rows out inside a page", async () => {
    const comboColumns: PackingBoxesMatrixColumn[] = ["S", "M", "L"].map(
      (size, index) => ({
        key: `c${index}`,
        base_variation_id: `v${index}`,
        base_size: size,
        base_sort_order: index,
        base_share_type_id: "veg",
        base_share_type_name: "Vegetables",
        base_share_type_short_name: "VEG",
        base_share_type_sort_index: 0,
        base_is_packed_bulk: false,
        add_ons: [
          { share_type_short_name: "FRU", size: "S" },
        ] as PackingBoxesMatrixColumn["add_ons"],
        count: 1,
      }),
    );
    const groups = groupComboColumns(comboColumns, t);
    const result = await layout(
      <Document>
        <Page size="A4">
          <ListPDFHeader
            pill="Packing"
            tenant={{ name: "Farm", email: "a@b.test", phone: "1" }}
          >
            {null}
          </ListPDFHeader>
          <ComboGroupHeaderRow groups={groups} comboWidth={60} thinBorderBottom />
          <ComboColumnHeaderRow
            columns={comboColumns}
            comboWidth={60}
            groupEdges={computeGroupEdges(groups)}
            t={t}
          />
        </Page>
      </Document>,
    );
    expect(result).toEqual({ isPdf: true, pages: 1 });
  }, 30_000);
});
