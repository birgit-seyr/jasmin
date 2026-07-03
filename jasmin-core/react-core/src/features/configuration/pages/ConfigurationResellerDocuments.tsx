import { lazy, Suspense, useMemo } from "react";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";

// ResellerDocPreviewButtons statically imports InvoicePDF +
// DeliveryNotePDF + OfferPDF — pulling @react-pdf/renderer into
// whatever loads it. Lazy-loading keeps the config page's eager
// bundle clean; the PDF chunk only loads when the user opens the
// reseller-documents config page (not when they open any OTHER
// config tab from the sidebar).
const ResellerDocPreviewButtons = lazy(
  () => import("@features/configuration/components/ResellerDocPreviewButtons"),
);
import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";

export default function ConfigurationResellerDocuments() {
  const { t } = useTranslation();

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "payment_and_numbering",
        title: t("settings.reseller.payment_numbering.title"),
        settings: [
          {
            key: "payment_terms_reseller_in_days",
            label: t("settings.reseller.payment_terms"),
            description: t("settings.reseller.payment_terms_desc"),
            type: "number",
            defaultValue: 14,
            min: 1,
            max: 365,
            suffix: t("common.days"),
          },
          {
            key: "order_number_prefix",
            label: t("settings.reseller.order_prefix"),
            description: t("settings.reseller.order_prefix_desc"),
            type: "input",
            defaultValue: "BE",
            maxLength: 10,
          },
          {
            key: "order_numbers_start_new_at_year_change",
            label: t("settings.reseller.order_numbers_reset"),
            description: t("settings.reseller.order_numbers_reset_desc"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "delivery_note_number_prefix",
            label: t("settings.reseller.delivery_note_prefix"),
            type: "input",
            defaultValue: "LS",
            maxLength: 10,
          },
          {
            key: "delivery_note_numbers_start_new_at_year_change",
            label: t("settings.reseller.delivery_note_reset"),
            description: t("settings.reseller.delivery_note_numbers_reset_desc"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "invoice_number_prefix",
            label: t("settings.reseller.invoice_prefix"),
            type: "input",
            defaultValue: "RE",
            maxLength: 10,
          },
          {
            key: "correction_invoice_number_prefix",
            label: t("settings.reseller.correction_invoice_prefix"),
            type: "input",
            defaultValue: "RK",
            maxLength: 10,
          },
          {
            key: "invoice_numbers_start_new_at_year_change",
            label: t("settings.reseller.invoice_reset"),
            description: t("settings.reseller.invoice_numbers_reset_desc"),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
      {
        category: "offer_settings",
        title: t("settings.reseller.offer_settings.title"),
        description: t("settings.reseller.offer_settings.description"),
        settings: [
          {
            key: "used_tiers_for_offers",
            label: t("settings.reseller.offer_tiers"),
            description: t("settings.reseller.offer_tiers_desc"),
            type: "tiers",
            defaultValue: [],
          },
          {
            key: "offer_prices_are_per_pu",
            label: t("settings.reseller.offer_prices_are_per_pu"),
            description: t("settings.reseller.offer_prices_are_per_pu_desc"),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
      {
        category: "document_footer",
        title: t("settings.reseller.footer.title"),
        settings: [
          {
            key: "left_column_footer_documents_reseller",
            label: t("settings.reseller.footer_left"),
            type: "richtext",
            description: t("settings.reseller.footer_left_description"),
            defaultValue: "",
            maxCharsPerLine: 40,
            maxLines: 5,
            placeholderKey: "settings.reseller.footer_left_placeholder",
          },
          {
            key: "middle_column_footer_documents_reseller",
            label: t("settings.reseller.footer_middle"),
            type: "richtext",
            description: t("settings.reseller.footer_middle_description"),
            defaultValue: "",
            maxCharsPerLine: 40,
            maxLines: 5,
            placeholderKey: "settings.reseller.footer_middle_placeholder",
          },
          {
            key: "right_column_footer_documents_reseller",
            label: t("settings.reseller.footer_right"),
            type: "richtext",
            description: t("settings.reseller.footer_right_description"),
            defaultValue: "",
            maxCharsPerLine: 40,
            maxLines: 5,
            placeholderKey: "settings.reseller.footer_right_placeholder",
          },
        ],
      },
      {
        category: "offer_text",
        title: t("settings.reseller.offer_text.title"),
        settings: [
          {
            key: "entry_line_1_offer_reseller",
            label: t("settings.reseller.offer_entry_1"),
            type: "richtext",
            description: t("settings.reseller.offer_entry_1_description"),
            defaultValue: "",
            placeholderKey: "settings.reseller.offer_entry_1_placeholder",
          },
          {
            key: "entry_line_2_offer_reseller",
            label: t("settings.reseller.offer_entry_2"),
            type: "richtext",
            description: t("settings.reseller.offer_entry_2_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.offer_entry_2_placeholder",
          },
          {
            key: "entry_line_3_offer_reseller",
            label: t("settings.reseller.offer_entry_3"),
            type: "richtext",
            description: t("settings.reseller.offer_entry_3_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.offer_entry_3_placeholder",
          },
          {
            key: "order_instructions_offer_reseller",
            label: t("settings.reseller.offer_order_instructions"),
            type: "richtext",
            description: t("settings.reseller.offer_order_instructions_description"),
            defaultValue: "",
            placeholderKey:
              "settings.reseller.offer_order_instructions_placeholder",
          },
          {
            key: "greeting_line_1_offer_reseller",
            label: t("settings.reseller.offer_greeting_1"),
            type: "richtext",
            description: t("settings.reseller.offer_greeting_1_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.offer_greeting_1_placeholder",
          },
          {
            key: "greeting_line_2_offer_reseller",
            label: t("settings.reseller.offer_greeting_2"),
            type: "richtext",
            description: t("settings.reseller.offer_greeting_2_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.offer_greeting_2_placeholder",
          },
          {
            key: "greeting_line_3_offer_reseller",
            label: t("settings.reseller.offer_greeting_3"),
            type: "richtext",
            description: t("settings.reseller.offer_greeting_3_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.offer_greeting_3_placeholder",
          },
        ],
      },
      {
        category: "delivery_note_text",
        title: t("settings.reseller.delivery_text.title"),
        settings: [
          {
            key: "entry_line_1_delivery_note_reseller",
            label: t("settings.reseller.delivery_entry_1"),
            type: "richtext",
            description: t("settings.reseller.delivery_entry_1_description"),
            defaultValue: "",
            placeholderKey: "settings.reseller.delivery_entry_1_placeholder",
            maxLines: 1,
            maxCharacters: 100,
          },
          {
            key: "entry_line_2_delivery_note_reseller",
            label: t("settings.reseller.delivery_entry_2"),
            type: "richtext",
            description: t("settings.reseller.delivery_entry_2_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.delivery_entry_2_placeholder",
          },
          {
            key: "entry_line_3_delivery_note_reseller",
            label: t("settings.reseller.delivery_entry_3"),
            type: "richtext",
            description: t("settings.reseller.delivery_entry_3_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.delivery_entry_3_placeholder",
          },
          {
            key: "greeting_line_1_delivery_note_reseller",
            label: t("settings.reseller.delivery_greeting_1"),
            type: "richtext",
            maxLines: 1,
            maxCharacters: 100,
            description: t("settings.reseller.delivery_greeting_1_description"),
            defaultValue: "",
            placeholderKey: "settings.reseller.delivery_greeting_1_placeholder",
          },
          {
            key: "greeting_line_2_delivery_note_reseller",
            label: t("settings.reseller.delivery_greeting_2"),
            type: "richtext",
            description: t("settings.reseller.delivery_greeting_2_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.delivery_greeting_2_placeholder",
          },
          {
            key: "greeting_line_3_delivery_note_reseller",
            label: t("settings.reseller.delivery_greeting_3"),
            type: "richtext",
            description: t("settings.reseller.delivery_greeting_3_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.delivery_greeting_3_placeholder",
          },
        ],
      },
      {
        category: "invoice_text",
        title: t("settings.reseller.invoice_text.title"),
        settings: [
          {
            key: "entry_line_1_invoice_reseller",
            label: t("settings.reseller.invoice_entry_1"),
            type: "richtext",
            description: t("settings.reseller.invoice_entry_1_description"),
            defaultValue: "",
            placeholderKey: "settings.reseller.invoice_entry_1_placeholder",
          },
          {
            key: "entry_line_2_invoice_reseller",
            label: t("settings.reseller.invoice_entry_2"),
            type: "richtext",
            description: t("settings.reseller.invoice_entry_2_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.invoice_entry_2_placeholder",
          },
          {
            key: "entry_line_3_invoice_reseller",
            label: t("settings.reseller.invoice_entry_3"),
            type: "richtext",
            description: t("settings.reseller.invoice_entry_3_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.invoice_entry_3_placeholder",
          },
          {
            key: "greeting_line_1_invoice_reseller",
            label: t("settings.reseller.invoice_greeting_1"),
            type: "richtext",
            description: t("settings.reseller.invoice_greeting_1_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.invoice_greeting_1_placeholder",
          },
          {
            key: "greeting_line_2_invoice_reseller",
            label: t("settings.reseller.invoice_greeting_2"),
            type: "richtext",
            description: t("settings.reseller.invoice_greeting_2_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.invoice_greeting_2_placeholder",
          },
          {
            key: "greeting_line_3_invoice_reseller",
            label: t("settings.reseller.invoice_greeting_3"),
            type: "richtext",
            description: t("settings.reseller.invoice_greeting_3_description"),
            defaultValue: "",
            maxLines: 1,
            maxCharacters: 100,
            placeholderKey: "settings.reseller.invoice_greeting_3_placeholder",
          },
        ],
      },
    ],
    [t],
  );

  return (
    <SettingsPage
      settingsConfig={settingsConfig}
      cardMaxWidth={900}
      withLockedSettings
      extraAfter={({ getSettingValue }) => (
        <Suspense fallback={<Spin />}>
          <ResellerDocPreviewButtons getSettingValue={getSettingValue} />
        </Suspense>
      )}
    />
  );
}
