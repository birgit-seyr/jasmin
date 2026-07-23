import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import PaymentCyclesCard from "@features/configuration/components/PaymentCyclesCard";
import SettingsPage from "@features/configuration/components/SettingsPage";
import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import { checkBic, checkIban, formatIbanError } from "@shared/utils/iban";

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
      {
        category: "sepa",
        title: t("tenant.sepa.title"),
        description: t("tenant.sepa.description"),
        settings: [
          {
            key: "iban",
            label: t("tenant.organization.iban"),
            description: t("tenant.organization.iban_desc"),
            type: "input",
            // ISO 13616 mod-97 + country-length check. Mirrors the
            // backend ``IBANValidator`` so the office gets immediate
            // feedback instead of seeing a save failure later. Empty
            // values pass through (the field is ``blank=True`` on the
            // model; "must be present" only applies at SEPA-export
            // time and is checked there).
            validate: (value: string) => {
              const result = checkIban(value);
              if (result.valid) return null;
              return formatIbanError(result.reasons, t);
            },
          },
          {
            // Creditor identifier issued to the organization by the
            // member bank (one per Genossenschaft). Format is
            // country-code + 2 check digits + 3-char business code +
            // identifier, e.g. ``DE98ZZZ09999999999``. Stamped into
            // every pain.008 file's ``CdtrSchmeId`` block — without
            // it the bank rejects the entire batch.
            key: "sepa_creditor_id",
            label: t("tenant.organization.sepa_creditor_id"),
            description: t("tenant.organization.sepa_creditor_id_desc"),
            type: "input",
          },
          {
            // Stamped into ``InitgPty/Nm`` and the creditor block of
            // every pain.008 file. ISO 20022 caps the field at 70
            // chars; longer names get truncated by the export.
            key: "sepa_creditor_name",
            label: t("tenant.organization.sepa_creditor_name"),
            description: t("tenant.organization.sepa_creditor_name_desc"),
            type: "input",
            maxLength: 70,
          },
          {
            // BIC of the COOPERATIVE'S bank (not the members'). The
            // ``sepaxml`` library requires this in its config even
            // though pain.008.001.02 marks the field as optional.
            // Bank tells the office this 8 or 11 character code when
            // they set up SEPA Direct Debit.
            key: "sepa_creditor_bic",
            label: t("tenant.organization.sepa_creditor_bic"),
            description: t("tenant.organization.sepa_creditor_bic_desc"),
            type: "input",
            maxLength: 11,
            // Same XSD pattern the pain.008 export enforces — flags an
            // invalid BIC at entry instead of failing the whole batch
            // export later. Empty passes (checked at export, like IBAN).
            validate: (value: string) =>
              checkBic(value).valid
                ? null
                : t("tenant.organization.sepa_creditor_bic_invalid"),
          },
          {
            // Rendered into every pain.008 file's ``Ustrd`` — the text the
            // member sees on their bank statement. The custom editor
            // surfaces placeholder chips + a live preview.
            key: "sepa_remittance_template",
            label: t("tenant.organization.sepa_remittance_template"),
            description: t("tenant.organization.sepa_remittance_template_desc"),
            type: "remittance_template",
            maxLength: 140,
          },

          {
            key: "sepa_collection_day_of_month",
            label: t("settings.payments.sepa_collection_day"),
            description: t("settings.payments.sepa_collection_day_desc"),
            type: "number",
            defaultValue: 5,
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
      <SettingsPage
        title={t("configuration.payments")}
        settingsConfig={settingsConfig}
      />
      <PaymentCyclesCard />
    </>
  );
}
