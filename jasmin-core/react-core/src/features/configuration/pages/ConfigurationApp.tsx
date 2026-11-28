import { Card, Col, Row, Space, Spin } from "antd";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useTranslation } from "react-i18next";
import {
  tenantsSettingsUpdateCurrentSettingsUpdate,
  tenantsTenantsPartialUpdate,
} from "@shared/api/generated/tenants/tenants";
import { AutoSaveIndicator } from "@shared/ui";
import { useAutoSave, useCapability, useTenant } from "@hooks/index";
import { SUPPORTED_LANGUAGES } from "@shared/i18n/languages";
import { notify } from "@shared/utils";
import HrSystemSettingsCard from "@features/configuration/components/HrSystemSettingsCard";
import {
  SettingsCategory,
  SettingsRenderer,
} from "@features/configuration/components/SettingsRenderer";
import {
  splitSettingsForSave,
  tenantToSaveablePayload,
  TENANT_SETTINGS_OVERLAY_KEYS,
  tenantToUISettings,
} from "./utils/tenantSettingsMapping";

/**
 * Options for the tenant language select. The code is appended to each
 * language's own name because this is a long settings form, where a bare
 * native language name is easy to skim past.
 */
const TENANT_LANGUAGE_OPTIONS = SUPPORTED_LANGUAGES.map((language) => ({
  value: language.code,
  label: `${language.name} (${language.code.toUpperCase()})`,
}));

export default function ConfigurationApp() {
  const [tenantData, setTenantData] = useState<Record<string, unknown>>({});
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);

  const { t } = useTranslation();
  const { tenant, getSetting, refreshTenant } = useTenant();

  // A tenant that uploads its weekly share amounts runs no subscriptions and
  // holds no member records, so the MEMBERS and ABOS modules would show empty
  // pages. Their navigation toggles are locked, and shown off
  // (``disabledDisplayValue``) because the modules are in fact hidden — the
  // stored preference is left untouched and returns when the flag is cleared.
  const weeklyUpload = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;
  // A host application that fixes the operating mode or the modules leaves
  // nothing to choose there.
  const offersOperatingModeChoice = useCapability("operating_mode_choice");
  const offersModuleChoice = useCapability("module_choice");

  const settingsConfig = useMemo<SettingsCategory[]>(
    () =>
      [
        {
          category: "navigation",
          title: t("settings.navigation.title"),
          settings: [
            {
              key: "navigation.show_members",
              label: t("settings.navigation.show_members"),
              type: "checkbox",
              defaultValue: true,
              disabled: weeklyUpload,
              disabledTooltip: t("settings.navigation.locked_by_weekly_upload"),
              disabledDisplayValue: false,
            },
            {
              key: "navigation.show_abos",
              label: t("settings.navigation.show_abos"),
              type: "checkbox",
              defaultValue: true,
              disabled: weeklyUpload,
              disabledTooltip: t("settings.navigation.locked_by_weekly_upload"),
              disabledDisplayValue: false,
            },
            {
              key: "navigation.show_commissioning",
              label: t("settings.navigation.show_commissioning"),
              type: "checkbox",
              defaultValue: true,
            },
            {
              key: "navigation.show_staff",
              label: t("settings.navigation.show_staff"),
              type: "checkbox",
              defaultValue: true,
            },
            {
              key: "navigation.show_warehouse",
              label: t("settings.navigation.show_warehouse"),
              type: "checkbox",
              defaultValue: true,
            },
            {
              key: "navigation.show_economics",
              label: t("settings.navigation.show_economics"),
              type: "checkbox",
              defaultValue: true,
            },
            {
              key: "navigation.show_cultivation",
              label: t("settings.navigation.show_cultivation"),
              type: "checkbox",
              defaultValue: true,
            },
          ],
        },
        // Which pages, settings and documents the farm needs follows from
        // whom it sells to, whether it buys in and whether it documents its
        // organic certification, so this sits right under the modules.
        {
          category: "sales",
          title: t("settings.commissioning.sales.title"),
          settings: [
            {
              key: "sells_to_resellers",
              label: t("settings.commissioning.sells_to_resellers"),
              description: t("settings.commissioning.sells_to_resellers_desc"),
              type: "checkbox",
              defaultValue: true,
            },
            {
              key: "has_markets",
              label: t("settings.commissioning.has_markets"),
              description: t("settings.commissioning.has_markets_desc"),
              type: "checkbox",
              defaultValue: false,
            },
            {
              key: "has_purchases",
              label: t("settings.commissioning.has_purchases"),
              description: t("settings.commissioning.has_purchases_desc"),
              type: "checkbox",
              defaultValue: true,
            },
            {
              key: "uses_organic_documentation",
              label: t("settings.commissioning.uses_organic_documentation"),
              description: t(
                "settings.commissioning.uses_organic_documentation_desc",
              ),
              type: "checkbox",
              defaultValue: true,
            },
          ],
        },
        // This one switch decides whether the tenant runs subscriptions at
        // all; switched on, it locks the members and subscriptions modules.
        {
          category: "operating_mode",
          title: t("settings.operating_mode.title"),
          settings: [
            {
              key: "uploads_weekly_share_amount",
              label: t("settings.commissioning.uploads_weekly_amount"),
              description: t(
                "settings.commissioning.uploads_weekly_amount_desc",
              ),
              type: "checkbox",
              defaultValue: false,
            },
          ],
        },
        {
          category: "general",
          title: t("settings.general.title"),
          settings: [
            {
              // Drives the backend's defaults too: the email templates and
              // the consent documents' language.
              key: "tenant_language",
              label: t("tenant.organization.tenant_language"),
              type: "select",
              options: TENANT_LANGUAGE_OPTIONS,
              defaultValue: "de",
            },
            {
              key: "currency",
              label: t("settings.general.currency"),
              type: "select",
              options: [
                { value: "EUR", label: "EUR" },
                { value: "CHF", label: "CHF" },
                { value: "USD", label: "USD" },
              ],
              defaultValue: "EUR",
            },

            {
              key: "date_format",
              label: t("settings.general.dateFormat"),
              type: "select",
              options: [
                { value: "DD.MM.YYYY", label: "DD.MM.YYYY" },
                { value: "DD/MM/YYYY", label: "DD/MM/YYYY" },
                { value: "YYYY-MM-DD", label: "YYYY-MM-DD" },
                { value: "MM-DD-YYYY", label: "MM-DD-YYYY" },
              ],
              defaultValue: "DD.MM.YYYY",
            },
            {
              key: "time_format",
              label: t("settings.general.timeFormat"),
              type: "select",
              options: [
                { value: "HH:mm", label: "HH:mm (24h, e.g. 14:30)" },
                { value: "HH:mm:ss", label: "HH:mm:ss (24h with seconds)" },
                { value: "hh:mm A", label: "hh:mm AM/PM (e.g. 02:30 PM)" },
                { value: "h:mm A", label: "h:mm AM/PM (e.g. 2:30 PM)" },
              ],
              defaultValue: "HH:mm",
            },
            {
              key: "csv_format",
              label: t("settings.general.csvFormat"),
              type: "select",
              options: [
                {
                  value: "de",
                  label: t("settings.general.csvFormat_de"),
                },
                {
                  value: "en",
                  label: t("settings.general.csvFormat_en"),
                },
              ],
              defaultValue: "de",
            },
            {
              key: "number_locale",
              label: t("settings.general.numberLocale"),
              type: "select",
              // BCP-47 tags for Intl.NumberFormat in the UI and PDFs; the
              // backend writes the amounts in its emails with the same tag.
              // Stored on Tenant.number_locale.
              options: [
                { value: "de-DE", label: "1.234,56" },
                { value: "de-CH", label: "1’234.56" },
                { value: "en-US", label: "1,234.56" },
                { value: "fr-FR", label: "1 234,56" },
              ],
              defaultValue: "de-DE",
            },
          ],
        },
        {
          category: "planning",
          title: t("settings.commissioning.planning.title"),
          settings: [
            {
              key: "allow_upload_for_data_lists",
              label: t("settings.commissioning.allow_upload_for_data_lists"),
              description: t(
                "settings.commissioning.allow_upload_for_data_lists_desc",
              ),

              type: "checkbox",
              defaultValue: false,
            },
          ],
        },

        // {
        //   category: "ai",
        //   title: t("settings.ai.title", "AI Settings"),
        //   settings: [
        //     {
        //       key: "ai.claude_enabled",
        //       label: t("settings.ai.claude_enabled", "Enable Claude AI"),
        //       type: "checkbox",
        //       disabled: true,
        //       defaultValue: false,
        //     },
        //   ],
        // },
      ].filter(
        (category) =>
          (offersOperatingModeChoice ||
            category.category !== "operating_mode") &&
          (offersModuleChoice || category.category !== "navigation"),
      ),
    [t, weeklyUpload, offersOperatingModeChoice, offersModuleChoice],
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

    const currentSettings = tenantToUISettings(
      tenant as Record<string, unknown>,
    );

    // Fill the TenantSettings fields from the stored row (current_settings), because
    // that row is what this form saves. The merged `settings` show the mode in effect,
    // which a host such as Tapir can force on; saving that back would store a choice
    // nobody made.
    const tenantSettingsOverlay =
      ((tenant as Record<string, unknown>).current_settings as
        | Record<string, unknown>
        | undefined) || {};
    for (const overlayKey of TENANT_SETTINGS_OVERLAY_KEYS) {
      if (overlayKey in tenantSettingsOverlay) {
        currentSettings[overlayKey] = tenantSettingsOverlay[overlayKey];
      }
    }
    // Dynamic: every saveable column on the Tenant payload flows through.
    // Add a new column to ``apps/shared/tenants/models.Tenant`` → it appears
    // here without an edit. The denylist of non-saveable keys (id, domains,
    // logo URL, etc.) lives in ``tenantSettingsMapping``.
    const currentTenantData: Record<string, unknown> = tenantToSaveablePayload(
      tenant as Record<string, unknown> | null | undefined,
    );

    setSettings(currentSettings);
    setTenantData(currentTenantData);
    setLoading(false);
    // Re-seed whenever the tenant OBJECT changes — not just on a different
    // id — so the auth-gated ``settings`` overlay that arrives later via
    // ``refreshTenantFull`` (the TENANT_SETTINGS_OVERLAY_KEYS block above) is
    // picked up. Keying on ``tenant?.id`` alone misses it: the slim anonymous
    // ``tenantsCurrentRetrieve`` sets the id first WITHOUT the overlay, and the
    // later merge keeps the same id so an id-only dep never re-fires, leaving
    // overlay-backed inputs on their stale defaults. The ``hasChanges ||
    // saving`` guard above still protects in-progress edits. (TenantContext
    // memoizes the value, so this only re-fires on a real data change.)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-seeds on tenant data, not on draft state
  }, [tenant]);

  // Stable refs for save handler
  const tenantDataRef = useRef(tenantData);
  tenantDataRef.current = tenantData;
  const settingsStateRef = useRef(settings);
  settingsStateRef.current = settings;

  // Save handler — uses refs to avoid depending on tenantData/settings.
  // ``useAutoSave`` owns the ``saving`` / ``hasChanges`` flags around
  // its own ``flush`` call; this body only does the actual PATCH(es).
  const handleSave = useCallback(async () => {
    const currentTenantId = tenantIdRef.current;
    if (!currentTenantId) return;

    try {
      const tenantId = String(currentTenantId);
      const currentTenantData = tenantDataRef.current;
      const currentSettings = settingsStateRef.current;
      const { tenantFields: mappedTenantFields, settingsOverlay } =
        splitSettingsForSave(currentSettings);

      // No file fields to strip here: ``currentTenantData`` already came
      // through ``tenantToSaveablePayload``, which drops every entry in
      // ``TENANT_FILE_FIELDS`` (a stored URL string must never be re-sent to an
      // ImageField — DRF answers "the submitted data was not a file" and the
      // user sees a 400 on whatever unrelated field they were editing).
      // Picture uploads use the multipart ``usePictureUpload`` hook instead.
      const dataToSend = { ...currentTenantData };

      await tenantsTenantsPartialUpdate(tenantId, {
        ...dataToSend,
        ...mappedTenantFields,
      });

      // ``TenantSettings`` overlay (versioned, not on the Tenant row) needs
      // its own endpoint. Skip the call when nothing in the overlay changed.
      if (Object.keys(settingsOverlay).length > 0) {
        await tenantsSettingsUpdateCurrentSettingsUpdate({
          settings: settingsOverlay,
        });
      }

      // Pull the freshly-saved tenant row + settings overlay into
      // TenantContext. ``refreshTenant`` routes to the auth-gated full
      // payload whenever a tenant id is known (see TenantContext), so
      // both the Tenant scalars edited above and any ``TenantSettings``
      // overlay keys flow back into ``getSetting(...)`` correctly.
      await refreshTenant();
    } catch (error) {
      notify.error(t("common.error_saving_data"));
      // Re-throw so useAutoSave keeps the change dirty instead of flipping the
      // indicator to "saved" over a change that didn't persist.
      throw error;
    }
  }, [refreshTenant, t]);

  // Single source of truth for the autosave debounce + flags. Per-field
  // ``markChanged(field.type)`` drives the per-change delay policy
  // inside the hook (dropdown / checkbox → instant, text → 500 ms).
  const { hasChanges, saving, markChanged } = useAutoSave({
    enabled: !loading && Boolean(tenant?.id),
    save: handleSave,
  });

  const handleSettingChange = useCallback(
    (key: string, value: unknown, fieldType?: string) => {
      setSettings((prev) => {
        const newSettings = { ...prev };
        const keys = key.split(".");

        if (keys.length === 1) {
          newSettings[keys[0]] = value;
        } else if (keys.length === 2) {
          if (!newSettings[keys[0]]) newSettings[keys[0]] = {};
          (newSettings[keys[0]] as Record<string, unknown>)[keys[1]] = value;
        }

        return newSettings;
      });
      markChanged(fieldType);
    },
    [markChanged],
  );

  // Settings keys are dotted paths (at most one level of nesting, mirroring
  // ``handleSettingChange``), so resolve them segment by segment.
  const getSettingValue = useCallback(
    (key: string, defaultValue?: unknown) => {
      let value: unknown = settings;
      for (const segment of key.split(".")) {
        value = (value as Record<string, unknown>)?.[segment];
      }
      return value !== undefined ? value : defaultValue;
    },
    [settings],
  );

  if (loading) {
    return (
      <div className="loading-placeholder">
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div>
      <h1>{t("configuration.app")}</h1>

      <AutoSaveIndicator saving={saving} hasChanges={hasChanges} />

      <Space direction="vertical" size="middle" className="w-full">
        {settingsConfig.map((category) => (
          <Fragment key={category.category}>
            <Card
              title={category.title}
              className="settings-card-header page-narrow"
              styles={{ body: { padding: "16px" } }}
            >
              <Row gutter={[12, 12]}>
                {category.settings.map((setting) => (
                  <Col
                    span={SettingsRenderer.getColumnSpan(setting)}
                    key={setting.key}
                  >
                    <div className="settings-item">
                      {SettingsRenderer.renderInput(
                        setting,
                        getSettingValue(setting.key, setting.defaultValue),
                        (value) =>
                          handleSettingChange(setting.key, value, setting.type),
                      )}
                      {SettingsRenderer.renderDescription(setting)}
                    </div>
                  </Col>
                ))}
              </Row>
            </Card>
            {/* Another interface, saved field by field rather than with the
                page's autosave; it serves the staff module alone. Where the
                host fixes the modules, the form's stored choice doesn't
                count, the module in effect does. */}
            {category.category === "planning" &&
              Boolean(
                offersModuleChoice
                  ? getSettingValue("navigation.show_staff", true)
                  : getSetting("navigation.show_staff", true),
              ) && <HrSystemSettingsCard />}
          </Fragment>
        ))}
      </Space>
    </div>
  );
}
