import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ShareArticle } from "@shared/api/generated/models";
import type {
  EditableColumnConfig,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";
import { pickTierPriceFromAmount } from "@shared/utils/tierPrice";
import { useUnitOptions } from "@hooks/useUnitOptions";
import type { ShareArticleOption } from "../useShareArticles";
import { useShareArticles } from "../useShareArticles";
import {
  computeShareArticlePatch,
  computeUnitChangePatch,
  type ArticleDefaults,
} from "./articleDefaults";

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
   * default autofill from ``articleDefaults``.
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
  articleDefaults?: ArticleDefaults;
  /**
   * Side-effect run AFTER the built-in article/unit autofill patches are
   * written. Lets a page layer on context-specific autofill (e.g. the planning
   * grid's per-variation default amounts from ``DefaultShareArticleInShare``)
   * WITHOUT discarding the pricing / PU / crate patch that ``articleDefaults``
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
   * ``[1]`` fallback when the setting is empty / unset). The old
   * ``[1, 3, 5]`` default silently bumped non-tier tenants into
   * 3-tier pricing.
   */
  finalTiers?: number[];
  disableCondition?: ((record: Record<string, unknown>) => boolean) | null;
  tooltip?: boolean | null;
}

/**
 * `ShareArticleOption` is `ShareArticle | ArticleForOrderItem` (plus value/label).
 * Only the full `ShareArticle` form carries pricing / defaults; the lightweight
 * `ArticleForOrderItem` does not. This helper narrows the option to the
 * `ShareArticle` shape so we can safely read those fields.
 */
const asShareArticle = (
  option: ShareArticleOption,
): ShareArticle & { value: string; label: string } =>
  option as ShareArticle & { value: string; label: string };

export const useShareArticleColumn = (config: ShareArticleColumnConfig = {}) => {
  const {
    filters = {},
    overrides = {},
    onFieldChange = null,
    showFruitsOnly = false,
    showVegsOnly = false,
    showFruitsAndVegs = false,
    articleDefaults,
    onDefaultsApplied,
    finalTiers,
    disableCondition = null,
    tooltip = null,
  } = config;

  const { t } = useTranslation();

  const { unitOptions } = useUnitOptions();
  const { shareArticles, loading: shareArticlesLoading } =
    useShareArticles(filters);

  const isLoading = shareArticlesLoading;

  /**
   * Default share-article-change handler. Seeds ``unit`` from the
   * article's ``default_movement_unit`` (falling back to the first
   * unit option, then KG), then writes the context-specific patch:
   * amount-per-PU + crate + prices + description.
   */
  const handleShareArticleChange = useCallback(
    (
      shareArticleValue: string,
      _record: Record<string, unknown>,
      form: FormInstance,
    ) => {
      if (!articleDefaults) return {};
      const selected = shareArticles.find((a) => a.value === shareArticleValue);
      if (!selected) return {};
      const article = asShareArticle(selected);

      const defaultUnit =
        article.default_movement_unit || unitOptions[0]?.value || "KG";

      form.setFieldsValue({ unit: defaultUnit });
      form.setFieldsValue(
        computeShareArticlePatch(articleDefaults, article, defaultUnit),
      );
      onDefaultsApplied?.(shareArticleValue, defaultUnit, form);
      return {};
    },
    [articleDefaults, shareArticles, unitOptions, onDefaultsApplied],
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
      if (!articleDefaults) return {};
      const articleId =
        (form.getFieldValue("share_article") as string | undefined) ??
        (form.getFieldValue("share_article_name") as string | undefined);
      if (!articleId) return {};
      const selected = shareArticles.find((a) => a.value === articleId);
      if (!selected) return {};
      const article = asShareArticle(selected);
      form.setFieldsValue(computeUnitChangePatch(articleDefaults, article, newUnit));
      onDefaultsApplied?.(articleId, newUnit, form);
      return {};
    },
    [articleDefaults, shareArticles, onDefaultsApplied],
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
   * No-op for ``"harvest"`` / ``"purchase"`` contexts (those pages
   * don't have ``price_per_unit`` columns).
   */
  const handleAmountChange = useCallback(
    (
      newAmount: unknown,
      _record: Record<string, unknown>,
      form: FormInstance,
    ) => {
      if (articleDefaults !== "reseller") return {};
      const pricePerUnit = pickTierPriceFromAmount(
        newAmount as number | string | null | undefined,
        form.getFieldValue("amount_per_pu") as number | string | null,
        {
          price_1: form.getFieldValue("price_1") as number | string | null,
          price_2: form.getFieldValue("price_2") as number | string | null,
          price_3: form.getFieldValue("price_3") as number | string | null,
        },
        finalTiers,
      );
      form.setFieldsValue({ price_per_unit: pricePerUnit });
      return {};
    },
    [articleDefaults, finalTiers],
  );

  const fieldChangeHandler = useMemo(() => {
    if (onFieldChange) return onFieldChange;
    if (articleDefaults) return handleShareArticleChange;
    return undefined;
  }, [onFieldChange, articleDefaults, handleShareArticleChange]);

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
