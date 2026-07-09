import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningCrateNetPricesList,
  useCommissioningShareArticlesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CrateNetPrice,
  ShareArticle,
} from "@shared/api/generated/models";
import { useCurrency } from "@hooks/index";
import ExportCsvAtDateModal, {
  type ExportCsvColumn,
  type PriceColumn,
} from "./ExportCsvAtDateModal";
import { useSharePriceCsvColumns } from "./useSharePriceCsvColumns";

/**
 * Combined "all share articles + extras + crates with prices at a date"
 * CSV export.
 *
 * The dedicated per-type exports remain in place. This modal is the
 * one-stop panorama: every article (regular + extra) AND every crate,
 * joined with the active price row at the chosen date. It reuses the
 * generic `ExportCsvAtDateModal` shell (pick-a-date → Load → build CSV) and
 * only supplies its own two-source row merge + per-column renders.
 *
 * - Articles use the backend join: `?include_extra=true&get_price_info=true
 *   &price_date=YYYY-MM-DD` annotates each row with the matching
 *   `ShareArticleNetPrice` columns.
 * - Crates: the crate-prices endpoint doesn't accept a date param yet, so
 *   we fetch all crate price rows and filter client-side to the one row
 *   per crate whose `[valid_from, valid_until]` window covers the date.
 *
 * Price column labels reuse `useSharePriceCsvColumns()` so this CSV stays
 * in lockstep with `ExportCsvPricesShareArticle` (same labels, same
 * tier numbers from `used_tiers_for_offers`).
 */

const yesNo = (lang: string) =>
  lang.startsWith("de") ? ["ja", "nein"] : ["yes", "no"];

interface ExportCsvAllArticlesProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Row supplier: merges the two data sources into one row stream. Articles carry
 * a `__row_type: "article"` tag; crate rows are the active price per crate at
 * the loaded date (client-side `[valid_from, valid_until]` window filter).
 */
function useAllArticleRowsAtDate(loadedDate: string | null) {
  // ── Articles + their active price (server-side join) ───────────────
  const { data: articleData, isLoading: articleLoading } =
    useCommissioningShareArticlesList(
      {
        include_extra: true,
        get_price_info: true,
        is_data_list: true,
        price_date: loadedDate ?? "",
      },
      { query: { enabled: !!loadedDate } },
    );

  // ── Crate prices (client-side date filter) ────────────────────────
  const { data: cratePricesRaw, isLoading: crateLoading } =
    useCommissioningCrateNetPricesList(
      {},
      { query: { enabled: !!loadedDate } },
    );

  const loading = articleLoading || crateLoading;
  const isReady = !!loadedDate && !loading;

  const activeCratePrices = useMemo<CrateNetPrice[]>(() => {
    if (!loadedDate || !cratePricesRaw) return [];
    const rows = cratePricesRaw as CrateNetPrice[];
    const seen = new Set<string>();
    const result: CrateNetPrice[] = [];
    for (const row of rows) {
      const crateId = row.crate;
      if (!crateId || seen.has(crateId)) continue;
      const from = row.valid_from ?? "";
      const until = row.valid_until ?? "";
      if (from && from > loadedDate) continue;
      if (until && until < loadedDate) continue;
      seen.add(crateId);
      result.push(row);
    }
    return result;
  }, [cratePricesRaw, loadedDate]);

  const rows = useMemo<Record<string, unknown>[] | null>(() => {
    if (!isReady) return null;
    const articles = (articleData ?? []) as ShareArticle[];
    const articleRows: Record<string, unknown>[] = articles.map((a) => ({
      ...(a as unknown as Record<string, unknown>),
      __row_type: "article",
    }));
    const crateRows: Record<string, unknown>[] = activeCratePrices.map((p) => ({
      __row_type: "crate",
      name: p.name ?? p.short_name ?? "",
      tax_rate: p.tax_rate ?? "",
      crate_price: p.price ?? "",
    }));
    return [...articleRows, ...crateRows];
  }, [isReady, articleData, activeCratePrices]);

  return { rows, isLoading: loading };
}

export default function ExportCsvAllArticles({
  open,
  onClose,
}: ExportCsvAllArticlesProps) {
  const { t, i18n } = useTranslation();
  const { currencySymbol } = useCurrency();

  // Reuses the same price-column hook the standalone price export uses,
  // so the per-price labels are identical (`USt., €/kg, €/Stk., €/Bund,
  // €/kg ab N VPE, …`).
  const pricePart = useSharePriceCsvColumns();

  const columns = useMemo<ExportCsvColumn[]>(() => {
    const [yes, no] = yesNo(i18n.language || "de");
    const boolToText = (v: unknown) =>
      v === true ? yes : v === false ? no : "";
    const isArticle = (row: Record<string, unknown>) =>
      row.__row_type === "article";
    const articleOnly =
      (inner: (v: unknown, row: Record<string, unknown>) => unknown) =>
      (v: unknown, row: Record<string, unknown>) =>
        isArticle(row) ? inner(v, row) : "";

    const articleMeta: ExportCsvColumn[] = [
      {
        key: "__row_type",
        label: t("commissioning.row_type_label"),
        render: (v: unknown) =>
          v === "crate"
            ? t("commissioning.row_type_crate")
            : t("commissioning.row_type_article"),
      },
      { key: "name", label: t("commissioning.name") },
      {
        key: "default_movement_unit",
        label: t("commissioning.unit"),
        render: articleOnly((v) => v ?? ""),
      },
      {
        key: "is_extra",
        label: t("commissioning.is_extra"),
        render: articleOnly(boolToText),
      },
      {
        key: "is_purchased",
        label: t("commissioning.is_purchased"),
        render: articleOnly(boolToText),
      },
      {
        key: "is_active",
        label: t("commissioning.is_active"),
        render: articleOnly(boolToText),
      },
      {
        key: "is_sold_to_resellers",
        label: t("commissioning.for_resellers"),
        render: articleOnly(boolToText),
      },
      {
        key: "share_option",
        label: t("commissioning.share_option_label"),
        render: articleOnly((v) => v ?? ""),
      },
      {
        key: "share_option2",
        label: t("commissioning.share_option_2_label"),
        render: articleOnly((v) => v ?? ""),
      },
      {
        key: "share_option3",
        label: t("commissioning.share_option_3_label"),
        render: articleOnly((v) => v ?? ""),
      },
    ];

    // Shared price columns (tax_rate + 12 price fields). For crate rows,
    // only `tax_rate` is meaningful — every other price field renders
    // empty since CrateNetPrice doesn't have those fields.
    const sharedPrices: ExportCsvColumn[] = pricePart.map((c: PriceColumn) => ({
      key: c.key,
      label: c.label,
      render:
        c.key === "tax_rate"
          ? undefined
          : (v: unknown, row: Record<string, unknown>) =>
              isArticle(row) ? (v ?? "") : "",
    }));

    const crateOnly: ExportCsvColumn[] = [
      {
        key: "crate_price",
        label: `${t("commissioning.crate_price")} (${currencySymbol})`,
      },
    ];

    return [...articleMeta, ...sharedPrices, ...crateOnly];
  }, [t, i18n.language, pricePart, currencySymbol]);

  return (
    <ExportCsvAtDateModal
      open={open}
      onClose={onClose}
      title={t("commissioning.export_all_articles_combined")}
      filenamePrefix="all_articles_with_prices"
      columns={columns}
      useRows={useAllArticleRowsAtDate}
      width={520}
      loadedMessageKey="commissioning.articles_loaded"
    />
  );
}
