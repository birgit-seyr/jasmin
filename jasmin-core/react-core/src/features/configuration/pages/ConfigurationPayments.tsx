import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";
import PaymentCyclesCard from "@features/configuration/components/PaymentCyclesCard";

export default function ConfigurationPayments() {
  const { t } = useTranslation();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "billing_strategy",
        title: t("settings.payments.strategy.title"),
        description: t("settings.payments.strategy.description"),
        settings: [
          {
            key: "billing_strategy",
            label: t("settings.payments.billing_strategy"),
            description: t("settings.payments.billing_strategy_desc"),
            type: "select",
            options: [
              {
                value: "EXACT_PER_PERIOD",
                label: t("settings.payments.strategy_exact"),
              },
              {
                // SMOOTHED is temporarily withdrawn: when a cancellation / joker
                // / opt-out shrinks a term total below already-locked charges it
                // over-collects, and there is no refund/credit model to settle
                // the money owed back yet. Kept visible (greyed) so the option
                // isn't silently lost, but unselectable until that lands.
                value: "SMOOTHED",
                label: t("settings.payments.strategy_smoothed_disabled"),
                disabled: true,
              },
            ],
            defaultValue: "EXACT_PER_PERIOD",
          },
          {
            key: "bills_joker_deliveries",
            label: t("settings.payments.bills_joker_deliveries"),
            description: t("settings.payments.bills_joker_deliveries_desc"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "allows_solidarity_pricing",
            label: t("settings.payments.allows_solidarity_pricing"),
            description: t("settings.payments.allows_solidarity_pricing_desc"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "requires_paper_signature_for_sepa_mandate",
            label: t(
              "settings.payments.requires_paper_signature_for_sepa_mandate",
            ),
            description: t(
              "settings.payments.requires_paper_signature_for_sepa_mandate_desc",
            ),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
      {
        category: "jokers",
        title: t("settings.commissioning.jokers.title"),
        settings: [
          {
            key: "uses_jokers",
            label: t("settings.commissioning.uses_jokers"),
            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "default_amount_of_jokers",
            label: t("settings.commissioning.default_amount_jokers"),
            description: t(
              "settings.commissioning.default_amount_jokers_description",
            ),
            type: "number",
            defaultValue: 3,
            min: 0,
            max: 20,
            // Hidden while the joker feature is off — the value has no
            // meaning when ``uses_jokers`` is false.
            visibleIf: (getValue) => Boolean(getValue("uses_jokers", true)),
          },
          {
            key: "uses_donation_jokers",
            label: t("settings.commissioning.donation_jokers"),
            type: "checkbox",
            defaultValue: false,
            // Donation jokers are a sub-feature of jokers; hide the
            // toggle when the parent feature is off.
            visibleIf: (getValue) => Boolean(getValue("uses_jokers", true)),
          },
          {
            key: "default_amount_of_donation_jokers",
            label: t(
              "settings.commissioning.default_amount_of_donation_jokers",
            ),
            description: t(
              "settings.commissioning.default_amount_of_donation_jokers_description",
            ),
            type: "number",
            defaultValue: 3,
            min: 0,
            max: 20,
            visibleIf: (getValue) =>
              Boolean(getValue("uses_jokers", true)) &&
              Boolean(getValue("uses_donation_jokers", false)),
          },
        ],
      },
      {
        category: "billing_due",
        title: t("settings.payments.due.title"),
        settings: [
          {
            key: "billing_due_day_of_month",
            label: t("settings.payments.due_day"),
            description: t("settings.payments.due_day_desc"),
            type: "number",
            defaultValue: 1,
            min: 1,
            max: 28,
          },
        ],
      },
    ],
    [t],
  );

  return (
    <>
      <SettingsPage settingsConfig={settingsConfig} />
      <PaymentCyclesCard />
    </>
  );
}
