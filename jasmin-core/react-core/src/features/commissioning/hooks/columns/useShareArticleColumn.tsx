import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { hasTierPrice, pickTierPriceFromAmount } from "@shared/utils/tierPrice";
import { useShareArticles } from "../useShareArticles";
import {
  computeShareArticlePatch,
  computeUnitChangePatch,
  type ArticleAutofillContext,
} from "./articleDefaults";

// Stable defaults, so a caller that passes no overrides keeps the column memo
// below intact across renders.
const NO_FILTERS: Record<string, unknown> = {};
const NO_OVERRIDES: Record<string, unknown> = {};

interface FormInstance {
  setFieldsValue: (values: Record<string, unknown>) => void;
  getFieldValue: (field: string) => unknown;
  setFieldValue: (field: string, value: unknown) => void;
}

interface ShareArticleColumnConfig {
  filters?: Record<string, unknown>;
  overrides?: Record<string, unknown>;
  /**
   * Custom share_article-change handler. If set, overrides the
   * default autofill from ``autofillContext``.
   */
  onFieldChange?: ((...args: unknown[]) => unknown) | null;
  showFruitsOnly?: boolean;
  showVegsOnly?: boolean;
  showFruitsAndVegs?: boolean;
  /**
   * Drives the share-article + unit-change autofill. Picks the
   * matching ``default_<unit>_per_pu_<side>`` and (where applicable)
   * crate / price-tier fields from the article. See
   * ``hooks/columns/articleDefaults.ts`` for the dispatch table.
   * Omit to disable autofill entirely.
   */
  autofillContext?: ArticleAutofillContext;
  /**
   * Side-effect run AFTER the built-in article/unit autofill patches are
   * written. Lets a page layer on context-specific autofill (e.g. the planning
   * grid's per-variation default amounts from ``DefaultShareArticleInShare``)
   * WITHOUT discarding the pricing / PU / crate patch that ``autofillContext``
   * produces. Invoked on article change (with the freshly-seeded default unit)
   * and on unit change (with the new unit), each with the resolved article id +
   * unit + form. No-op if omitted.
   */
  onDefaultsApplied?: (
    articleId: string,
    unit: string,
    form: FormInstance,
  ) => void;
  /**
   * Tier thresholds used by ``handleAmountChange`` (reseller context
   * only). The array is interpreted as [tier1, tier2, tier3]; a typed
   * amount picks ``price_3`` if ``finalTiers[2]`` is set and
   * ``amount >= finalTiers[2]``, else ``price_2`` if ``finalTiers[1]``
   * is set and ``amount >= finalTiers[1]``, else ``price_1``.
   *
   * **Defaults to `[]` (single-tier mode)** — only ``price_1`` is ever
   * picked, regardless of quantity. Pages should pass the tenant's
   * ``used_tiers_for_offers`` setting through (with their own
   * ``[1]`` fallback when the setting is empty / unset).
   */
  finalTiers?: number[];
  disableCondition?: ((record: Record<string, unknown>) => boolean) | null;
  tooltip?: boolean | null;
}

export const useShareArticleColumn = (config: ShareArticleColumnConfig = {}) => {
  const {
    filters = NO_FILTERS,
    overrides = NO_OVERRIDES,
    onFieldChange = null,
    showFruitsOnly = false,
    showVegsOnly = false,
    showFruitsAndVegs = false,
    autofillContext,
    onDefaultsApplied,
    finalTiers,
    disableCondition = null,
    tooltip = null,
  } = config;

  const { t } = useTranslation();

  const { shareArticles, loading: shareArticlesLoading } =
    useShareArticles(filters);

  const isLoading = shareArticlesLoading;

  /**
   * Default share-article-change handler. Seeds ``unit`` from the
   * article's ``default_movement_unit``, then writes the context-specific
   * patch: amount-per-PU + crate + prices + description.
   */
  const handleShareArticleChange = useCallback(
    (
      shareArticleValue: string,
      _record: Record<string, unknown>,
      form: FormInstance,
    ) => {
      if (!autofillContext) return {};
      const article = shareArticles.find((a) => a.value === shareArticleValue);
      if (!article) return {};

      const defaultUnit = article.default_movement_unit;

      form.setFieldsValue({ unit: defaultUnit });
      form.setFieldsValue(
        computeShareArticlePatch(autofillContext, article, defaultUnit),
      );
      onDefaultsApplied?.(shareArticleValue, defaultUnit, form);
      return {};
    },
    [autofillContext, shareArticles, onDefaultsApplied],
  );

  /**
   * Unit-change handler. Wire into ``useAmountUnitSizeColumns`` via
   * ``overrides.unit.onFieldChange``. Reads the row's current
   * share_article id from the form, then writes the unit-change patch
   * (amount-per-PU + prices — crate is preserved).
   */
  const handleUnitChange = useCallback(
    (
      newUnit: string,
      _record: Record<string, unknown>,
      form: FormInstance,
    ) => {
      if (!autofillContext) return {};
      const articleId =
        (form.getFieldValue("share_article") as string | undefined) ??
        (form.getFieldValue("share_article_name") as string | undefined);
      if (!articleId) return {};
      const article = shareArticles.find((a) => a.value === articleId);
      if (!article) return {};
      form.setFieldsValue(computeUnitChangePatch(autofillContext, article, newUnit));
      onDefaultsApplied?.(articleId, newUnit, form);
      return {};
    },
    [autofillContext, shareArticles, onDefaultsApplied],
  );

  /**
   * Amount-change handler — reseller context only. Wire into
   * ``useAmountUnitSizeColumns.overrides.amount.onFieldChange``. Reads
   * ``price_1/2/3`` and ``amount_per_pu`` from the form, converts the
   * typed amount (KG / PCS / BUNCH) to a PU count via
   * ``amount / amount_per_pu``, picks the matching tier against
   * ``finalTiers`` (which are PU-based), and writes ``price_per_unit``
   * so the user sees the live per-unit price as they type the amount.
   *
   * Only picking an article or a unit puts the tier prices on the form,
   * so a saved line has none: its price stays as saved instead of
   * dropping to 0, and so does a price the office typed for an article
   * without tier prices.
   *
   * No-op for ``"harvest"`` / ``"purchase"`` contexts (those pages
   * don't have ``price_per_unit`` columns).
   */
  const handleAmountChange = useCallback(
    (
      newAmount: unknown,
      _record: Record<string, unknown>,
      form: FormInstance,
    ) => {
      if (autofillContext !== "reseller") return {};
      const prices = {
        price_1: form.getFieldValue("price_1") as number | string | null,
        price_2: form.getFieldValue("price_2") as number | string | null,
        price_3: form.getFieldValue("price_3") as number | string | null,
      };
      if (!hasTierPrice(prices)) return {};
      const pricePerUnit = pickTierPriceFromAmount(
        newAmount as number | string | null | undefined,
        form.getFieldValue("amount_per_pu") as number | string | null,
        prices,
        finalTiers,
      );
      form.setFieldsValue({ price_per_unit: pricePerUnit });
      return {};
    },
    [autofillContext, finalTiers],
  );

  const fieldChangeHandler = useMemo(() => {
    if (onFieldChange) return onFieldChange;
    if (autofillContext) return handleShareArticleChange;
    return undefined;
  }, [onFieldChange, autofillContext, handleShareArticleChange]);

  const columnTitle = useMemo(() => {
    const titleText = t(
      showFruitsOnly
        ? "commissioning.fruit"
        : showVegsOnly
        ? "commissioning.vegetable"
        : showFruitsAndVegs
        ? "commissioning.vegetables_and_fruits"
        : "commissioning.share_articles"
    );

    if (tooltip) {
      return (
        <span>
          {titleText}
          <ToolTipIcon
            title={t("tooltip.share_article_harvest_planing_shares")}
          />
        </span>
      );
    }

    return titleText;
  }, [t, showFruitsOnly, showVegsOnly, showFruitsAndVegs, tooltip]);

  const shareArticleColumn = useMemo(
    () => ({
      title: columnTitle,
      dataIndex: "share_article_name",
      key: "share_article_name",
      inputType: "select",
      required: true,
      width: "14em",
      align: "left" as const,
      options: shareArticles as unknown as SelectOption[],
      fixed: true,
      foreignKey: {
        valueField: "share_article",
        displayField: "share_article_name",
      },
      onFieldChange: fieldChangeHandler,
      sortable: true,
      disabled: disableCondition,
      ...overrides,
    } as EditableColumnConfig<TableRecord>),
    [
      columnTitle,
      shareArticles,
      fieldChangeHandler,
      overrides,
      disableCondition,
    ]
  );

  return {
    shareArticleColumn,
    shareArticles,
    /** Wire into ``useAmountUnitSizeColumns.overrides.unit.onFieldChange``. */
    handleUnitChange,
    /**
     * Wire into ``useAmountUnitSizeColumns.overrides.amount.onFieldChange``
     * for live per-unit price (reseller context only — no-op otherwise).
     */
    handleAmountChange,
    isLoading,
  };
};
