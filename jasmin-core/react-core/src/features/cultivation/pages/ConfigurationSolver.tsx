import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationSolverSettingsList,
  cultivationSolverSettingsSavePartialUpdate,
} from "@shared/api/generated/cultivation/cultivation";
import SettingsPage from "@features/configuration/components/SettingsPage";
import type { SettingsCategory } from "@features/configuration/components/SettingsRenderer";

/**
 * Tuning page for the placement optimizer: how long it may run, which optional
 * constraints apply, and how it weighs competing goals. Backed by the
 * cultivation ``solver_settings`` singleton rather than tenant settings, so the
 * standard settings shell is pointed at that endpoint.
 */
export default function ConfigurationSolver() {
  const { t } = useTranslation();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "solver_runtime",
        title: t("cultivation.solver_runtime"),
        settings: [
          {
            key: "solver_max_time_seconds",
            label: t("cultivation.solver_max_time_seconds"),
            description: t("cultivation.solver_max_time_seconds_description"),
            type: "number",
            defaultValue: 60,
            min: 1,
            max: 900,
          },
          {
            key: "default_num_solutions",
            label: t("cultivation.default_num_solutions"),
            description: t("cultivation.default_num_solutions_description"),
            type: "number",
            defaultValue: 4,
            min: 1,
            max: 20,
          },
          {
            key: "solver_workers",
            label: t("cultivation.solver_workers"),
            description: t("cultivation.solver_workers_description"),
            type: "number",
            defaultValue: 8,
            min: 1,
            max: 32,
          },
        ],
      },
      {
        category: "solver_features",
        title: t("cultivation.solver_features"),
        settings: [
          {
            key: "enable_planting_line_homogeneity",
            label: t("cultivation.enable_planting_line_homogeneity"),
            description: t(
              "cultivation.enable_planting_line_homogeneity_description",
            ),
            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "enable_fleece",
            label: t("cultivation.enable_fleece"),
            description: t("cultivation.enable_fleece_description"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "enable_line_dispersion",
            label: t("cultivation.enable_line_dispersion"),
            description: t("cultivation.enable_line_dispersion_description"),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
      {
        category: "solver_weights",
        title: t("cultivation.solver_weights"),
        description: t("cultivation.solver_weights_description"),
        settings: [
          {
            key: "weight_plots_used",
            label: t("cultivation.weight_plots_used"),
            type: "number",
            defaultValue: 100,
            min: 0,
            max: 1000,
          },
          {
            key: "weight_beds_used",
            label: t("cultivation.weight_beds_used"),
            type: "number",
            defaultValue: 10,
            min: 0,
            max: 1000,
          },
          {
            key: "weight_beds_per_batch",
            label: t("cultivation.weight_beds_per_batch"),
            type: "number",
            defaultValue: 5,
            min: 0,
            max: 1000,
          },
          {
            key: "weight_compact_span",
            label: t("cultivation.weight_compact_span"),
            type: "number",
            defaultValue: 3,
            min: 0,
            max: 1000,
          },
          {
            key: "weight_line_dispersion",
            label: t("cultivation.weight_line_dispersion"),
            type: "number",
            defaultValue: 1,
            min: 0,
            max: 1000,
            visibleIf: (getValue) =>
              Boolean(getValue("enable_line_dispersion", false)),
          },
          {
            key: "weight_fleece_count",
            label: t("cultivation.weight_fleece_count"),
            type: "number",
            defaultValue: 10,
            min: 0,
            max: 1000,
            visibleIf: (getValue) => Boolean(getValue("enable_fleece", false)),
          },
        ],
      },
    ],
    [t],
  );

  return (
    <SettingsPage
      title={t("cultivation.solver_settings")}
      settingsConfig={settingsConfig}
      fetchSettings={() => cultivationSolverSettingsList()}
      saveSettings={(data) => cultivationSolverSettingsSavePartialUpdate(data)}
    />
  );
}
