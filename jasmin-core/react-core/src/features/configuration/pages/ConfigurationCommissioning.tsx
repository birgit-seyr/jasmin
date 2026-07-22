import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";

export default function ConfigurationCommissioning() {
  const { t } = useTranslation();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "logistics",
        title: t("settings.commissioning.logistics.title"),
        settings: [
          {
            key: "packing_mode",
            label: t("settings.commissioning.packing_mode"),

            type: "select",
            defaultValue: "BOXES",
            options: [
              {
                value: "BOXES",
                label: t("settings.commissioning.packing_mode_boxes"),
              },
              {
                value: "BULK",
                label: t("settings.commissioning.packing_mode_bulk"),
              },
              {
                value: "MIXED",
                label: t("settings.commissioning.packing_mode_mixed"),
              },
            ],
          },

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
            step: 0.1,
            precision: 2,
          },
          {
            key: "number_packing_stations",
            label: t("settings.commissioning.number_packing_stations"),
            type: "number",
            defaultValue: 1,
            min: 1,
            max: 50,
          },
        ],
      },
      {
        category: "layout",
        title: t("settings.commissioning.layout.title"),
        settings: [
          {
            key: "show_size_column",
            label: t("settings.commissioning.show_size_column"),
            type: "checkbox",
            defaultValue: true,
          },

          {
            key: "distribute_forecast_by_weight",
            label: t("settings.commissioning.distribute_forecast_by_weight"),
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
          {
            key: "show_seller_name_of_share_article_in_share_for_member_on_page",
            label: t("settings.commissioning.show_seller_name_in_share"),
            type: "checkbox",
            defaultValue: true,
          },
          {
            // Wired into ``PlanningHarvestSharesBase.tsx`` as the initial
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
        ],
      },
      {
        category: "sales",
        title: t("settings.commissioning.sales.title"),
        settings: [
          {
            key: "sells_to_resellers",
            label: t("settings.commissioning.sells_to_resellers"),
            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "has_markets",
            label: t("settings.commissioning.has_markets"),
            type: "checkbox",
            defaultValue: false,
            disabled: true,
          },
        ],
      },
      {
        category: "tax_rates",
        title: t("settings.commissioning.tax_rates.title"),
        description: t("settings.commissioning.tax_rates.description"),
        settings: [
          {
            key: "default_tax_rate_articles",
            label: t("settings.commissioning.default_tax_rate_articles"),
            type: "number",
            defaultValue: 7,
            min: 0,
            max: 100,
            step: 0.1,
            precision: 2,
          },
          {
            key: "default_tax_rate_crates",
            label: t("settings.commissioning.default_tax_rate_crates"),
            type: "number",
            defaultValue: 19,
            min: 0,
            max: 100,
            step: 0.1,
            precision: 2,
          },
          {
            key: "default_tax_rate_shares",
            label: t("settings.commissioning.default_tax_rate_shares"),
            type: "number",
            defaultValue: 7,
            min: 0,
            max: 100,
            step: 0.1,
            precision: 2,
          },
        ],
      },
    ],
    [t],
  );

  return (
    <SettingsPage
      title={t("configuration.commissioning")}
      settingsConfig={settingsConfig}
    />
  );
}
