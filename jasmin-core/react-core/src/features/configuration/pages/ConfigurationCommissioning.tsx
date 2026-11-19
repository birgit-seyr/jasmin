import { Button } from "antd";
import type { TFunction } from "i18next";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  SettingConfig,
  SettingsCategory,
} from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";
import { useTaxesArticles } from "@features/commissioning/hooks/useTaxesArticles";
import { StationBulkPercentagesModal } from "@features/configuration/modals";
import { useCapability, useTenant } from "@hooks/index";

/** A default tax rate setting, in percent. */
function taxRateSetting(
  key: string,
  label: string,
  defaultValue: number,
): SettingConfig {
  return {
    key,
    label,
    type: "number",
    defaultValue,
    min: 0,
    max: 100,
    step: 0.1,
    precision: 2,
  };
}

/** The default tax rates of what the farm charges tax on; no category where
 *  it charges none of them. */
function taxRatesCategory(
  t: TFunction,
  charged: { articles: boolean; crates: boolean; shares: boolean },
): SettingsCategory[] {
  const settings = [
    ...(charged.articles
      ? [
          taxRateSetting(
            "default_tax_rate_articles",
            t("settings.commissioning.default_tax_rate_articles"),
            7,
          ),
        ]
      : []),
    ...(charged.crates
      ? [
          taxRateSetting(
            "default_tax_rate_crates",
            t("settings.commissioning.default_tax_rate_crates"),
            19,
          ),
        ]
      : []),
    ...(charged.shares
      ? [
          taxRateSetting(
            "default_tax_rate_shares",
            t("settings.commissioning.default_tax_rate_shares"),
            7,
          ),
        ]
      : []),
  ];
  if (settings.length === 0) return [];
  return [
    {
      category: "tax_rates",
      title: t("settings.commissioning.tax_rates.title"),
      description: t("settings.commissioning.tax_rates.description"),
      settings,
    },
  ];
}

/**
 * The packing settings of the farm's packing mode: the loose packing lists'
 * surcharges where shares go out loose, the packing stations where they go
 * out pre-packed, both where the sizes differ. No packing mode to pick: it
 * follows from how the office packs each share size.
 */
function packingCategory(
  t: TFunction,
  packs: { loose: boolean; boxed: boolean },
  onOpenStationPercentages: () => void,
): SettingsCategory {
  return {
    category: "packing",
    title: t("settings.commissioning.packing.title"),
    settings: [
      ...(packs.loose
        ? [
            {
              key: "percentage_added_to_bulk_packing_list",
              label: t(
                "settings.commissioning.percentage_added_to_bulk_packing_list",
              ),
              description: t(
                "settings.commissioning.percentage_added_to_bulk_packing_list_description",
              ),
              type: "number",
              defaultValue: 0,
              min: 0,
              max: 500,
              step: 1,
              precision: 0,
              extra: (
                <Button onClick={onOpenStationPercentages}>
                  {t("settings.commissioning.station_bulk_percentages.button")}
                </Button>
              ),
            },
          ]
        : []),
      ...(packs.boxed
        ? [
            {
              key: "number_packing_stations",
              label: t("settings.commissioning.number_packing_stations"),
              description: t(
                "settings.commissioning.number_packing_stations_description",
              ),
              type: "number",
              defaultValue: 1,
              min: 1,
              max: 50,
            },
          ]
        : []),
    ],
  };
}

export default function ConfigurationCommissioning() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const [stationPercentagesOpen, setStationPercentagesOpen] = useState(false);
  // The mode the share sizes are packed in: BOXES, BULK or MIXED.
  const packingMode = getSetting("packing_mode", "BOXES");
  const packsLoose = packingMode === "BULK" || packingMode === "MIXED";
  const packsBoxed = packingMode === "BOXES" || packingMode === "MIXED";
  // Members see their boxes on jasmin's own member pages, which a host
  // without jasmin's logins doesn't have, and a seller's name only on what
  // the farm buys in.
  const showsSellerNames =
    useCapability("user_accounts") &&
    getSetting("has_purchases", true) !== false;
  // A farm that imports its share amounts sets no share prices, the only
  // thing the default share tax rate fills in.
  const importsShareAmounts = Boolean(
    getSetting("uploads_weekly_share_amount", false),
  );
  // Crates are charged to resellers only, the one thing the default crate tax
  // rate fills in.
  const sellsToResellers = getSetting("sells_to_resellers", true) !== false;
  const taxesArticles = useTaxesArticles();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "share_planning",
        title: t("settings.commissioning.share_planning.title"),
        settings: [
          {
            // Wired into ``PlanningShareContentBase.tsx`` as the initial
            // value of ``planningMode`` (lazy useState seed). The
            // ``PlanningModeSelector`` lets the office override per week,
            // matching the description copy below.
            key: "default_planning_granularity",
            label: t("settings.commissioning.default_planning_mode"),
            description: t(
              "settings.commissioning.default_planning_mode_description",
            ),
            type: "select",
            options: [
              {
                value: "basic",
                label: t("settings.commissioning.default_planning_mode_basic"),
              },
              {
                value: "tours",
                label: t("settings.commissioning.default_planning_mode_tours"),
              },
              {
                value: "stations",
                label: t(
                  "settings.commissioning.default_planning_mode_stations",
                ),
              },
            ],
            defaultValue: "basic",
          },
          {
            key: "distribute_forecast_by_weight",
            label: t("settings.commissioning.distribute_forecast_by_weight"),
            description: t(
              "settings.commissioning.distribute_forecast_by_weight_description",
            ),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "show_summary_in_harvest_share_planning_on_top",
            label: t(
              "settings.commissioning.show_summary_in_harvest_share_planning_on_top",
            ),
            type: "checkbox",
            defaultValue: true,
          },
        ],
      },
      packingCategory(t, { loose: packsLoose, boxed: packsBoxed }, () =>
        setStationPercentagesOpen(true),
      ),
      {
        category: "work_steps",
        title: t("settings.commissioning.work_steps.title"),
        settings: [
          {
            key: "show_washing",
            label: t("settings.commissioning.show_washing"),
            description: t("settings.commissioning.show_washing_description"),
            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "show_cleaning",
            label: t("settings.commissioning.show_cleaning"),
            description: t("settings.commissioning.show_cleaning_description"),
            type: "checkbox",
            defaultValue: true,
          },
        ],
      },

      {
        category: "lists",
        title: t("settings.commissioning.lists.title"),
        settings: [
          {
            key: "show_size_column",
            label: t("settings.commissioning.show_size_column"),
            type: "checkbox",
            defaultValue: true,
          },
        ],
      },
      ...(showsSellerNames
        ? [
            {
              category: "member_pages",
              title: t("settings.commissioning.member_pages.title"),
              settings: [
                {
                  key: "show_seller_name_of_share_article_in_share_for_member_on_page",
                  label: t("settings.commissioning.show_seller_name_in_share"),
                  type: "checkbox",
                  defaultValue: true,
                },
              ],
            },
          ]
        : []),
      ...taxRatesCategory(t, {
        articles: taxesArticles,
        crates: sellsToResellers,
        shares: !importsShareAmounts,
      }),
    ],
    [
      t,
      packsLoose,
      packsBoxed,
      showsSellerNames,
      taxesArticles,
      sellsToResellers,
      importsShareAmounts,
    ],
  );

  return (
    <>
      <SettingsPage
        title={t("configuration.commissioning")}
        settingsConfig={settingsConfig}
      />
      <StationBulkPercentagesModal
        open={stationPercentagesOpen}
        onClose={() => setStationPercentagesOpen(false)}
      />
    </>
  );
}
