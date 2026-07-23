import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useCurrency } from "@hooks/index";
import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";

export default function ConfigurationMembers() {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "registration",
        title: t("settings.members.registration.title"),
        settings: [
          {
            // Public self-service registration on the login page. OFF (default)
            // hides the register buttons AND makes /api/register/* refuse
            // server-side (SelfRegistrationEnabled permission) — the flag is a
            // real control, not only a hidden button.
            key: "allows_self_registration",
            label: t("settings.members.allows_self_registration"),
            description: t("settings.members.allows_self_registration_desc"),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
      // The standalone "Probemitglieder erlauben" toggle was dropped
      // in migration 0020 — whether trial members can exist is
      // derived from the two trial-subscription settings on
      // ConfigurationSubscriptions
      // (``allows_trial_subscriptions`` ∧
      // ``allows_trial_subscriptions_for_trial_members``). The trial-member
      // concept exists solely to enable trial subscriptions, so a
      // separate toggle would only allow inconsistent states.
      {
        category: "coop_shares",
        title: t("settings.members.coop_shares.title"),
        settings: [
          {
            key: "has_coop_shares",
            label: t("settings.members.has_coop_shares"),
            description: t("settings.members.has_coop_shares_desc"),
            type: "checkbox",
            defaultValue: true,
            // Locked for now — tenants who turn coop-shares off
            // need a migration path for existing CoopShare rows,
            // GenG Mitgliederliste exit handling, and Subscription
            // pricing that no longer carries the share-equity
            // assumption. Until that path exists, keep the toggle
            // visible (so the office sees the setting exists) but
            // unchangeable. Flip back to editable when the
            // disable-coop-shares migration story is finalized.
            disabled: true,
          },
          {
            key: "value_one_coop_share",
            label: t("settings.members.value_one_share"),
            description: t("settings.members.value_one_share_desc"),
            type: "number",
            defaultValue: 100,
            min: 1,
            max: 10000,
            // Whole-unit integer (matches the backend PositiveIntegerField).
            step: 1,
            precision: 0,
            suffix: currencySymbol,
            visibleIf: (getValue) => Boolean(getValue("has_coop_shares", true)),
          },
          {
            key: "min_number_coop_shares",
            label: t("settings.members.min_shares"),
            description: t("settings.members.min_shares_desc"),
            type: "number",
            defaultValue: 3,
            min: 1,
            max: 100,
            visibleIf: (getValue) => Boolean(getValue("has_coop_shares", true)),
          },
          {
            key: "max_number_coop_shares",
            label: t("settings.members.max_shares"),
            description: t("settings.members.max_shares_desc"),
            type: "number",
            defaultValue: 100,
            min: 1,
            max: 1000,
            visibleIf: (getValue) => Boolean(getValue("has_coop_shares", true)),
          },
          {
            key: "retention_period_cancelled_members_coop_shares_in_months",
            label: t("settings.members.coop_payback_retention"),
            description: t("settings.members.coop_payback_retention_desc"),
            type: "number",
            defaultValue: 0,
            min: 0,
            max: 240,
            step: 1,
            precision: 0,
            suffix: t("settings.members.months_suffix"),
            visibleIf: (getValue) => Boolean(getValue("has_coop_shares", true)),
          },
        ],
      },
      {
        category: "loans",
        title: t("settings.members.loans.title"),
        settings: [
          {
            key: "uses_member_loans",
            label: t("settings.members.uses_member_loans"),
            description: t("settings.members.uses_member_loans_desc"),
            type: "checkbox",
            defaultValue: false,
            disabled: true,
          },
        ],
      },
      {
        category: "paper_signature",
        title: t("settings.members.paper_signature.title"),
        settings: [
          {
            key: "requires_paper_signature_for_membership",
            label: t(
              "settings.members.requires_paper_signature_for_membership",
            ),
            description: t(
              "settings.members.requires_paper_signature_for_membership_desc",
            ),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "requires_paper_signature_for_cancellation_of_membership",
            label: t(
              "settings.members.requires_paper_signature_for_cancellation_of_membership",
            ),
            description: t(
              "settings.members.requires_paper_signature_for_cancellation_of_membership_desc",
            ),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
    ],
    [t, currencySymbol],
  );

  return (
    <SettingsPage
      title={t("configuration.members")}
      settingsConfig={settingsConfig}
    />
  );
}
