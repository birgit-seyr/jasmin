import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";

const EXCLUSIVE_SETTINGS: Record<string, string> = {
  subscriptions_end_at_end_of_season: "subscriptions_end_after_one_year",
  subscriptions_end_after_one_year: "subscriptions_end_at_end_of_season",
};

export default function ConfigurationSubscriptions() {
  const { t } = useTranslation();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "subscriptions",
        title: t("settings.commissioning.subscriptions.title"),
        settings: [
          {
            key: "subscriptions_end_at_end_of_season",
            label: t("settings.commissioning.end_at_season_end"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "season_start_week",
            label: t("settings.commissioning.season_start_week"),
            // Stored as ISO calendar week so the same value drives
            // every year's ``valid_until`` derivation in Abos.tsx
            // (Monday of that week → -1 day → preceding Sunday).
            type: "number",
            min: 1,
            max: 53,
            visibleIf: (getValue) =>
              Boolean(getValue("subscriptions_end_at_end_of_season", true)),
          },
          {
            key: "subscriptions_end_after_one_year",
            label: t("settings.commissioning.end_after_year"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "subscriptions_are_auto_renewed",
            label: t("settings.commissioning.auto_renewed"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "min_weeks_to_cancel_before_ending",
            label: t("settings.commissioning.min_weeks_cancel"),
            description: t(
              "settings.commissioning.min_weeks_cancel_description",
            ),
            type: "number",
            defaultValue: 6,
            min: 0,
            max: 52,
            visibleIf: (getValue) =>
              Boolean(getValue("subscriptions_are_auto_renewed", true)),
          },
          {
            // Tenant-wide gate for the on-off (per-delivery opt-in)
            // mechanism. When True, ``ShareTypeVariationModal``
            // exposes two columns (``requires_optin``,
            // ``optin_deadline_days_before_delivery``) and the
            // backend accepts ``requires_optin=True`` writes. When
            // False, the columns disappear and the backend rejects
            // any save that would flip ``requires_optin=True``.
            // Existing on-off variations stay configured but their
            // toggles are inert until the flag flips back on.
            key: "allows_share_type_variation_optin",
            label: t(
              "settings.commissioning.allows_share_type_variation_optin",
            ),
            description: t(
              "settings.commissioning.allows_share_type_variation_optin_desc",
            ),
            type: "checkbox",
            defaultValue: false,
          },
          {
            // Gates the whole waiting-list flow. When off, at-capacity share
            // types can't be subscribed to (no offers, no queue) and the
            // waiting-list UI is hidden throughout the app.
            key: "allows_waiting_list_for_subscriptions",
            label: t(
              "settings.commissioning.allows_waiting_list_for_subscriptions",
            ),
            description: t(
              "settings.commissioning.allows_waiting_list_for_subscriptions_desc",
            ),
            type: "checkbox",
            defaultValue: true,
          },
          {
            // How long ANY draft subscription holds its station-day slot
            // before the reservation lapses — governs every capacity
            // reservation, independent of the waiting list, so it's always
            // shown.
            key: "reservation_ttl_days",
            label: t("settings.commissioning.reservation_ttl_days"),
            description: t("settings.commissioning.reservation_ttl_days_desc"),
            type: "number",
            defaultValue: 14,
            min: 0,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_waiting_list_for_subscriptions", false)),
          },
        ],
      },
      {
        category: "trial_subscriptions",
        title: t("settings.subscriptions.trial.title"),
        description: t("settings.subscriptions.trial.description"),
        settings: [
          {
            key: "allows_trial_subscriptions",
            label: t("settings.subscriptions.allows_trial_subscriptions"),

            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "allowed_trial_subscription_duration",
            label: t(
              "settings.subscriptions.allowed_trial_subscription_duration",
            ),
            description: t(
              "settings.subscriptions.allowed_trial_subscription_duration_desc",
            ),
            type: "number",
            defaultValue: 4,
            min: 1,
            max: 52,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
          {
            key: "allows_trial_subscriptions_for_trial_members",
            label: t(
              "settings.subscriptions.allows_trial_subscriptions_for_trial_members",
            ),
            description: t(
              "settings.subscriptions.allows_trial_subscriptions_for_trial_members_desc",
            ),
            type: "checkbox",
            defaultValue: true,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
          {
            key: "info_sentence_about_trial_subscriptions",
            label: t(
              "settings.subscriptions.info_sentence_about_trial_subscriptions",
            ),
            description: t(
              "settings.subscriptions.info_sentence_about_trial_subscriptions_desc",
            ),
            type: "input",
            defaultValue: "",
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
          {
            key: "uses_jokers_for_trial_subscriptions",
            label: t(
              "settings.subscriptions.uses_jokers_for_trial_subscriptions",
            ),
            description: t(
              "settings.subscriptions.uses_jokers_for_trial_subscriptions_desc",
            ),
            type: "checkbox",
            defaultValue: false,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
        ],
      },
    ],
    [t],
  );

  return (
    <SettingsPage
      title={t("configuration.subscriptions")}
      settingsConfig={settingsConfig}
      onBeforeSettingChange={(key, value, setSetting) => {
        const opposite = EXCLUSIVE_SETTINGS[key];
        if (opposite && value === true) {
          setSetting(opposite, false);
        }
      }}
    />
  );
}
