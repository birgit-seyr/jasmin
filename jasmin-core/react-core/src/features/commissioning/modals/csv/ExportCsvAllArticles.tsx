import { DownloadOutlined } from "@ant-design/icons";
import { Button, DatePicker, Empty, Modal, Spin } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningCrateNetPricesList,
  useCommissioningShareArticlesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CrateNetPrice,
  ShareArticle,
} from "@shared/api/generated/models";
import { useCurrency, useDateFormat, useTenant } from "@hooks/index";
import {
  buildCsvString,
  downloadCsvBlob,
  resolveCsvDialect,
} from "@shared/utils";
import type { PriceColumn } from "./ExportCsvAtDateModal";
import { useSharePriceCsvColumns } from "./useSharePriceCsvColumns";

/**
 * Combined "all share articles + extras + crates with prices at a date"
 * CSV export.
 *
 * The dedicated per-type exports remain in place. This modal is the
 * one-stop panorama: every article (regular + extra) AND every crate,
 * joined with the active price row at the chosen date.
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

interface Column {
  key: string;
  label: string;
  /** Optional value transform (boolean → ja/nein, null → "", etc.). */
  render?: (value: unknown, row: Record<string, unknown>) => unknown;
}

const yesNo = (lang: string) =>
  lang.startsWith("de") ? ["ja", "nein"] : ["yes", "no"];

interface ExportCsvAllArticlesProps {
  open: boolean;
  onClose: () => void;
}

export default function ExportCsvAllArticles({
  open,
  onClose,
}: ExportCsvAllArticlesProps) {
  const { t, i18n } = useTranslation();
  const { getSetting } = useTenant();
  const { currencySymbol } = useCurrency();
  const { dateFormat } = useDateFormat();
  const dialect = useMemo(
    () => resolveCsvDialect(getSetting("csv_format", "de") as string),
    [getSetting],
  );

  const [selectedDate, setSelectedDate] = useState<Dayjs>(dayjs());
  const [loadedDate, setLoadedDate] = useState<string | null>(null);

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

  // ── Merge into one row stream ─────────────────────────────────────
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

  // ── Columns ───────────────────────────────────────────────────────
  // Reuses the same price-column hook the standalone price export uses,
  // so the per-price labels are identical (`USt., €/kg, €/Stk., €/Bund,
  // €/kg ab N VPE, …`). New `*_label` keys avoid colliding with the
  // `commissioning.share_option` namespace, which is a nested object of
  // share-option translations, not a scalar string.
  const pricePart = useSharePriceCsvColumns();

  const columns = useMemo<Column[]>(() => {
    const [yes, no] = yesNo(i18n.language || "de");
    const boolToText = (v: unknown) =>
      v === true ? yes : v === false ? no : "";
    const isArticle = (row: Record<string, unknown>) =>
      row.__row_type === "article";
    const articleOnly = (
      inner: (v: unknown, row: Record<string, unknown>) => unknown,
    ) =>
      (v: unknown, row: Record<string, unknown>) =>
        isArticle(row) ? inner(v, row) : "";

    const articleMeta: Column[] = [
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
    const sharedPrices: Column[] = pricePart.map((c: PriceColumn) => ({
      key: c.key,
      label: c.label,
      render:
        c.key === "tax_rate"
          ? undefined
          : (v: unknown, row: Record<string, unknown>) =>
              isArticle(row) ? (v ?? "") : "",
    }));

    const crateOnly: Column[] = [
      {
        key: "crate_price",
        label: `${t("commissioning.crate_price")} (${currencySymbol})`,
      },
    ];

    return [...articleMeta, ...sharedPrices, ...crateOnly];
  }, [t, i18n.language, pricePart, currencySymbol]);

  const fetchAll = useCallback(() => {
    if (!selectedDate) return;
    setLoadedDate(selectedDate.format("YYYY-MM-DD"));
  }, [selectedDate]);

  const handleExport = useCallback(() => {
    if (!rows || rows.length === 0) return;
    const headers = columns.map((c) => c.label);
    const csvRows = rows.map((row) =>
      columns.map((c) => {
        const raw = row[c.key];
        return c.render ? c.render(raw, row) : (raw ?? "");
      }),
    );
    downloadCsvBlob(
      buildCsvString(headers, csvRows, dialect),
      `all_articles_with_prices_${selectedDate.format("YYYY-MM-DD")}`,
    );
    onClose();
  }, [rows, columns, selectedDate, onClose, dialect]);

  const handleClose = useCallback(() => {
    setLoadedDate(null);
    onClose();
  }, [onClose]);

  return (
    <Modal
      title={t("commissioning.export_all_articles_combined")}
      open={open}
      onCancel={handleClose}
      width={520}
      footer={[
        <Button key="cancel" onClick={handleClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="export"
          type="primary"
          className="download-button"
          icon={<DownloadOutlined />}
          disabled={!rows || rows.length === 0}
          onClick={handleExport}
        >
          {t("common.download")}
        </Button>,
      ]}
    >
      <div className="flex-center-y gap-12" style={{ marginBottom: 16 }}>
        <DatePicker
          value={selectedDate}
          onChange={(date) => {
            if (date) setSelectedDate(date);
          }}
          format={dateFormat}
          className="flex-1"
        />
        <Button type="primary" onClick={fetchAll} loading={loading}>
          {t("common.load")}
        </Button>
      </div>

      {loading && (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      )}

      {!loading && rows && rows.length === 0 && (
        <Empty description={t("common.no_data")} />
      )}

      {!loading && rows && rows.length > 0 && (
        <div style={{ color: "var(--color-success)", fontWeight: 500 }}>
          {t("commissioning.articles_loaded", {
            count: rows.length,
            defaultValue: "{{count}} rows loaded",
          })}
        </div>
      )}
    </Modal>
  );
}
