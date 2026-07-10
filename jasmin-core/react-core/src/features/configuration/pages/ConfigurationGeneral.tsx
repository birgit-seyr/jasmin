import { Card, Col, Row, Space, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Tenant } from "@shared/api/generated/models";
import type { Writable } from "@shared/api/typeHelpers";
import { tenantsTenantsPartialUpdate } from "@shared/api/generated/tenants/tenants";
import { AutoSaveIndicator, PictureUploadField, usePictureUpload } from "@shared/ui";
import { useAutoSave, useTenant } from "@hooks/index";
import { notify } from "@shared/utils";
import { checkBic, checkIban, formatIbanError } from "@shared/utils/iban";
import {
  SettingsCategory,
  SettingsRenderer,
} from "@features/configuration/components/SettingsRenderer";

const { Text } = Typography;

/**
 * Local draft of the tenant PATCH payload. Every writable ``Tenant``
 * column is allowed (so the seed + save paths are field-name checked
 * against the generated model); the two upload fields additionally
 * hold a ``File`` while an upload is pending — the API type only knows
 * the stored URL string.
 */
type TenantFormState = Partial<Writable<Omit<Tenant, "logo" | "bio_logo">>> & {
  logo?: File | string | null;
  bio_logo?: File | string | null;
};

export default function ConfigurationGeneral() {
  const [tenantData, setTenantData] = useState<TenantFormState>({});
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);

  const { t } = useTranslation();
  const { tenant, refreshTenant } = useTenant();

  // Branding uploads (logo + organic logo) go through the shared multipart
  // picture-upload hook — a separate, immediate PATCH decoupled from the JSON
  // autosave of the scalar fields below.
  const tenantEndpoint = `/api/tenants/tenants/${tenant?.id ?? ""}/`;

  const resolveMediaUrl = (value: string | null | undefined): string | null =>
    value
      ? value.startsWith("http")
        ? value
        : `${import.meta.env.VITE_API_URL || ""}${value}`
      : null;

  const logoPreviewUrl = resolveMediaUrl(tenant?.logo);
  const bioLogoPreviewUrl = resolveMediaUrl(tenant?.bio_logo);

  const { uploading: logoUploading, uploadPicture: uploadLogo } =
    usePictureUpload({
      endpoint: tenantEndpoint,
      fieldName: "logo",
      invalidate: refreshTenant,
      successMessage: t("tenant.files.logo_saved"),
      errorMessage: t("common.error_saving_data"),
    });
  const { uploading: bioLogoUploading, uploadPicture: uploadBioLogo } =
    usePictureUpload({
      endpoint: tenantEndpoint,
      fieldName: "bio_logo",
      invalidate: refreshTenant,
      successMessage: t("tenant.files.bio_logo_saved"),
      errorMessage: t("common.error_saving_data"),
    });

  // Memoize configurations
  const tenantFieldsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "basic_info",
        title: t("tenant.basic_info.title"),
        settings: [
          {
            key: "name",
            label: t("tenant.basic_info.name"),
            type: "input",
            required: true,
            defaultValue: "",
          },
          {
            key: "description",
            label: t("tenant.basic_info.description"),
            type: "textarea",
            defaultValue: "",
          },
          {
            key: "address",
            label: t("tenant.address.address"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "zip_code",
            label: t("tenant.address.zip_code"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "city",
            label: t("tenant.address.city"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "country",
            label: t("tenant.address.country"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "email",
            label: t("tenant.email"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "email_for_orders",
            label: t("tenant.email_for_orders"),
            type: "input",
            defaultValue: "",
          },

          {
            key: "phone_number",
            label: t("tenant.phone_number"),
            type: "input",
            defaultValue: "",
          },
        ],
      },
      {
        category: "organization",
        title: t("tenant.organization.title"),
        settings: [
          {
            key: "organic_control_number",
            label: t("tenant.organization.organic_control_number"),
            type: "input",
            defaultValue: "",
          },
          {
            // ``tenant_language`` is a column on ``Tenant`` (not on the
            // versioned ``TenantSettings``) so it saves through the
            // same ``tenantsTenantsPartialUpdate`` call as the other
            // org fields on this page. Drives backend defaults like
            // email templates and consent-document locale resolution.
            key: "tenant_language",
            label: t("tenant.organization.tenant_language"),
            type: "select",
            options: [
              { value: "de", label: "Deutsch (DE)" },
              { value: "en", label: "English (EN)" },
              { value: "fr", label: "Français (FR)" },
              { value: "it", label: "Italiano (IT)" },
            ],
            defaultValue: "de",
          },
          {
            key: "fiscal_year_start_month",
            label: t("tenant.organization.fiscal_year_start_month"),
            type: "select",
            options: [
              { value: 1, label: t("settings.months.january") },
              { value: 2, label: t("settings.months.february") },
              { value: 3, label: t("settings.months.march") },
              { value: 4, label: t("settings.months.april") },
              { value: 5, label: t("settings.months.may") },
              { value: 6, label: t("settings.months.june") },
              { value: 7, label: t("settings.months.july") },
              { value: 8, label: t("settings.months.august") },
              { value: 9, label: t("settings.months.september") },
              { value: 10, label: t("settings.months.october") },
              { value: 11, label: t("settings.months.november") },
              { value: 12, label: t("months.december") },
            ],
            defaultValue: 1,
          },
          {
            key: "uid",
            label: t("tenant.organization.uid"),
            type: "input",
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
      {
        // Public legal-notice ("Impressum") identity block. These columns
        // live on ``Tenant`` and save through the same autosave PATCH; the
        // public ``PublicLegalNotice`` page reads them (each section hides
        // when its field is blank, so eG-only rows can stay empty).
        category: "legal_notice",
        title: t("tenant.legal_notice.title"),
        description: t("tenant.legal_notice.description"),
        settings: [
          {
            key: "legal_form",
            label: t("tenant.legal_notice.legal_form"),
            description: t("tenant.legal_notice.legal_form_desc"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "register_type",
            label: t("tenant.legal_notice.register_type"),
            description: t("tenant.legal_notice.register_type_desc"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "register_number",
            label: t("tenant.legal_notice.register_number"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "register_court",
            label: t("tenant.legal_notice.register_court"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "legal_representatives",
            label: t("tenant.legal_notice.legal_representatives"),
            description: t("tenant.legal_notice.legal_representatives_desc"),
            type: "input",
            maxLength: 500,
            defaultValue: "",
          },
          {
            key: "supervisory_board",
            label: t("tenant.legal_notice.supervisory_board"),
            description: t("tenant.legal_notice.supervisory_board_desc"),
            type: "input",
            maxLength: 500,
            defaultValue: "",
          },
          {
            key: "content_responsible",
            label: t("tenant.legal_notice.content_responsible"),
            description: t("tenant.legal_notice.content_responsible_desc"),
            type: "input",
            defaultValue: "",
          },
          {
            key: "participates_in_dispute_resolution",
            label: t("tenant.legal_notice.participates_in_dispute_resolution"),
            description: t(
              "tenant.legal_notice.participates_in_dispute_resolution_desc",
            ),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "auditing_association",
            label: t("tenant.legal_notice.auditing_association"),
            description: t("tenant.legal_notice.auditing_association_desc"),
            type: "textarea",
            rows: 4,
            defaultValue: "",
          },
          {
            key: "professional_association",
            label: t("tenant.legal_notice.professional_association"),
            description: t("tenant.legal_notice.professional_association_desc"),
            type: "textarea",
            rows: 4,
            defaultValue: "",
          },
          {
            key: "legal_notice_extra_html",
            label: t("tenant.legal_notice.extra_html"),
            description: t("tenant.legal_notice.extra_html_desc"),
            type: "textarea",
            rows: 4,
            defaultValue: "",
          },
        ],
      },
    ],
    [t],
  );

  // Sync state from tenant data
  const tenantIdRef = useRef(tenant?.id);
  tenantIdRef.current = tenant?.id;

  useEffect(() => {
    if (!tenant?.id) {
      setLoading(false);
      return;
    }

    // Don't overwrite local changes
    if (hasChanges || saving) return;

    const currentSettings: Record<string, unknown> = {};
    // ``is_active`` is deliberately NOT seeded: it's a read-only column
    // and must not ride along on the PATCH payload.
    const currentTenantData: TenantFormState = {
      name: tenant.name || "",
      description: tenant.description || "",
      address: tenant.address || "",
      zip_code: tenant.zip_code || "",
      city: tenant.city || "",
      country: tenant.country || "",
      organic_control_number: tenant.organic_control_number || "",
      tenant_language: tenant.tenant_language || "",
      fiscal_year_start_month: tenant.fiscal_year_start_month || 1,
      iban: tenant.iban || "",
      sepa_creditor_id: tenant.sepa_creditor_id || "",
      sepa_creditor_name: tenant.sepa_creditor_name || "",
      sepa_creditor_bic: tenant.sepa_creditor_bic || "",
      sepa_remittance_template: tenant.sepa_remittance_template || "",
      uid: tenant.uid || "",
      phone_number: tenant.phone_number || "",
      email: tenant.email || "",
      email_for_orders: tenant.email_for_orders || "",
      website: tenant.website || "",
      days_until_payment_due: tenant.days_until_payment_due || 14,
      // Public legal-notice ("Impressum") identity block
      legal_form: tenant.legal_form || "",
      register_type: tenant.register_type || "",
      register_number: tenant.register_number || "",
      register_court: tenant.register_court || "",
      legal_representatives: tenant.legal_representatives || "",
      supervisory_board: tenant.supervisory_board || "",
      content_responsible: tenant.content_responsible || "",
      participates_in_dispute_resolution:
        tenant.participates_in_dispute_resolution ?? false,
      auditing_association: tenant.auditing_association || "",
      professional_association: tenant.professional_association || "",
      legal_notice_extra_html: tenant.legal_notice_extra_html || "",
    };

    setSettings(currentSettings);
    setTenantData(currentTenantData);
    setLoading(false);
    // Re-seed whenever the tenant OBJECT changes — not just on a different
    // id — so fields that arrive via ``refreshTenantFull`` (auth-gated block)
    // or a sibling-tab save for the SAME tenant are picked up. The
    // ``hasChanges || saving`` guard above still protects in-progress edits.
    // (TenantContext memoizes the value, so this only re-fires on a real data
    // change.) ``hasChanges``/``saving`` are intentionally omitted so merely
    // toggling them never re-seeds over a fresh draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant]);

  // Stable refs for save handler
  const tenantDataRef = useRef(tenantData);
  tenantDataRef.current = tenantData;
  const settingsStateRef = useRef(settings);
  settingsStateRef.current = settings;

  // Save handler — uses refs to avoid depending on tenantData/settings.
  // ``useAutoSave`` owns the ``saving`` / ``hasChanges`` flags so this
  // body only does the actual PATCH; the hook flips the flags around
  // its own ``flush`` call.
  const handleSave = useCallback(async () => {
    const currentTenantId = tenantIdRef.current;
    if (!currentTenantId) return;

    // Don't autosave a half-typed IBAN: the backend IBANValidator 400s on every
    // keystroke (e.g. "DE"), spamming error toasts. The inline field validation
    // already flags it; once it's a valid IBAN (or cleared) the next change
    // triggers a save that succeeds.
    const ibanValue = tenantDataRef.current.iban;
    if (
      typeof ibanValue === "string" &&
      ibanValue.trim() !== "" &&
      !checkIban(ibanValue).valid
    ) {
      return;
    }

    // Same guard for a half-typed creditor BIC: the pain.008 XSD pattern
    // rejects partial input, so don't autosave (and 400) until it's a valid
    // BIC or cleared. The inline field validation already flags it.
    const bicValue = tenantDataRef.current.sepa_creditor_bic;
    if (
      typeof bicValue === "string" &&
      bicValue.trim() !== "" &&
      !checkBic(bicValue).valid
    ) {
      return;
    }

    try {
      const tenantId = String(currentTenantId);
      const currentTenantData = tenantDataRef.current;

      // The upload fields never ride on this JSON PATCH: logo / bio_logo are
      // FileFields handled out-of-band by ``usePictureUpload`` (multipart), and
      // a stored URL string must not be re-sent to the ImageField.
      const { logo: _logo, bio_logo: _bio_logo, ...tenantFields } =
        currentTenantData;

      // Directional cast at the orval boundary: the autosave sends a
      // partial snapshot while the generated body type requires
      // ``name`` — the field names/types themselves are checked by
      // ``TenantFormState``.
      await tenantsTenantsPartialUpdate(tenantId, tenantFields as Tenant);

      // Pull the freshly-saved tenant row into TenantContext so the
      // form's next read of ``tenant.<field>`` reflects what's in the
      // DB. ``refreshTenant`` is wired (in TenantContext) to the
      // auth-gated full payload whenever a tenant id is known, so
      // operational fields like ``organic_control_number`` (which the
      // anonymous slim endpoint omits) flow through correctly.
      await refreshTenant();
    } catch (error) {
      console.error("Failed to save data:", error);
      notify.error(t("common.error_saving_data"));
      // Re-throw so useAutoSave keeps the change dirty instead of flipping the
      // indicator to "saved" over a change that didn't persist.
      throw error;
    }
  }, [refreshTenant, t]);

  // Single source of truth for the autosave debounce + flags. Per-field
  // ``markChanged(field.type)`` calls drive the per-change delay
  // policy inside the hook (dropdown / checkbox → instant, text → 500 ms).
  const { hasChanges, saving, markChanged } = useAutoSave({
    enabled: !loading && Boolean(tenant?.id),
    save: handleSave,
  });

  // SettingsRenderer drives fields by string key, so this single write
  // path bridges the stringly-keyed plumbing back into the typed state.
  const handleTenantFieldChange = useCallback(
    (key: string, value: unknown, fieldType?: string) => {
      setTenantData(
        (prev) =>
          ({
            ...prev,
            [key]: value,
          }) as TenantFormState,
      );
      markChanged(fieldType);
    },
    [markChanged],
  );

  // Get values with fallback (widening read for the string-keyed
  // SettingsRenderer plumbing).
  const getTenantFieldValue = useCallback(
    (key: string, defaultValue?: unknown) => {
      const values: Record<string, unknown> = tenantData;
      return values[key] !== undefined ? values[key] : defaultValue;
    },
    [tenantData],
  );

  return (
    <div style={{ padding: "16px" }}>
      <div style={{ marginBottom: "16px" }}>
        <AutoSaveIndicator saving={saving} hasChanges={hasChanges} />
      </div>
      <Space direction="vertical" size="middle" className="w-full">
        {/* Tenant Fields */}
        {tenantFieldsConfig.map((category) => (
          <Card
            key={category.category}
            title={category.title}
            className="settings-card-header page-narrow"
            styles={{ body: { padding: "16px" } }}
          >
            {category.description && (
              <Text
                type="secondary"
                style={{ display: "block", marginBottom: 12 }}
              >
                {category.description}
              </Text>
            )}
            <Row gutter={[12, 12]}>
              {category.settings.map((field) => (
                <Col
                  span={SettingsRenderer.getColumnSpan(field)}
                  key={field.key}
                >
                  <div style={{ padding: "4px 0" }}>
                    {SettingsRenderer.renderInput(
                      field,
                      getTenantFieldValue(field.key, field.defaultValue),
                      (value) =>
                        handleTenantFieldChange(field.key, value, field.type),
                    )}
                  </div>
                </Col>
              ))}
            </Row>
          </Card>
        ))}

        {/* Branding: Logo + Bio Logo */}
        <Card
          title={t("tenant.files.title")}
          className="settings-card-header page-narrow"
          styles={{ body: { padding: "16px" } }}
        >
          <Row gutter={[12, 12]}>
            <Col span={12}>
              <div style={{ padding: "4px 0" }}>
                <Text strong>{t("tenant.files.current_logo")}</Text>
                <div style={{ marginTop: 8 }}>
                  <PictureUploadField
                    pictureUrl={logoPreviewUrl}
                    uploading={logoUploading}
                    onUpload={uploadLogo}
                    previewVariant="inline"
                    showDelete={false}
                  />
                </div>
              </div>
            </Col>
            <Col span={12}>
              <div style={{ padding: "4px 0" }}>
                <Text strong>{t("tenant.files.current_bio_logo")}</Text>
                <div style={{ marginTop: 8 }}>
                  <PictureUploadField
                    pictureUrl={bioLogoPreviewUrl}
                    uploading={bioLogoUploading}
                    onUpload={uploadBioLogo}
                    previewVariant="inline"
                    showDelete={false}
                  />
                </div>
              </div>
            </Col>
          </Row>
        </Card>
      </Space>
    </div>
  );
}
