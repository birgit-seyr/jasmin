import { Card, Col, Row, Space, Spin } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useTranslation } from "react-i18next";
import type { Tenant } from "@shared/api/generated/models";
import {
  tenantsSettingsUpdateCurrentSettingsUpdate,
  tenantsTenantsPartialUpdate,
} from "@shared/api/generated/tenants/tenants";
import { AutoSaveIndicator } from "@shared/ui";
import { useAutoSave, useTenant } from "@hooks/index";
import { notify } from "@shared/utils";
import {
  SettingsCategory,
  SettingsRenderer,
} from "@features/configuration/components/SettingsRenderer";
import {
  DEFAULT_UI_SETTINGS,
  splitSettingsForSave,
  tenantToSaveablePayload,
  TENANT_SETTINGS_OVERLAY_KEYS,
  tenantToUISettings,
} from "./utils/tenantSettingsMapping";

export default function ConfigurationApp() {
  const [tenantData, setTenantData] = useState<Record<string, unknown>>({});
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);

  const { t } = useTranslation();
  const { tenant, refreshTenant } = useTenant();

  // Default settings
  const defaultSettings = DEFAULT_UI_SETTINGS as unknown as Record<
    string,
    unknown
  >;

  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "general",
        title: t("settings.general.title"),
        settings: [
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
            // BCP-47 tags consumed by Intl.NumberFormat in the UI / PDFs.
            // Backend persists this on TenantSettings.number_locale.
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
        category: "navigation",
        title: t("settings.navigation.title"),
        settings: [
          {
            key: "navigation.show_members",
            label: t("settings.navigation.show_members"),
            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "navigation.show_abos",
            label: t("settings.navigation.show_abos"),
            type: "checkbox",
            defaultValue: true,
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
      {
        category: "planning",
        title: t("settings.commissioning.planning.title"),
        settings: [
          {
            key: "allow_upload_for_data_lists",
            label: t("settings.commissioning.allow_upload_for_data_lists"),
            description: t("settings.commissioning.allow_upload_for_data_lists_desc"),

            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "uploads_weekly_share_amount",
            label: t("settings.commissioning.uploads_weekly_amount"),
            description: t("settings.commissioning.uploads_weekly_amount_desc"),

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

    const currentSettings = tenant
      ? tenantToUISettings(tenant as Record<string, unknown>)
      : defaultSettings;

    // Hydrate the versioned ``TenantSettings`` overlay values from the merged
    // ``settings`` dict the backend exposes on ``current-tenant`` so the form
    // shows the persisted value (and not just the default).
    const tenantSettingsOverlay =
      ((tenant as Record<string, unknown>)?.settings as
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

      // logo / favicon are FileFields — they never ride on this JSON PATCH (a
      // stored URL string must not be re-sent to the ImageField). A picture
      // upload from here goes through the shared multipart ``usePictureUpload``
      // hook, the same escape hatch ConfigurationGeneral uses.
      const dataToSend = { ...currentTenantData };
      delete dataToSend.logo;
      delete dataToSend.favicon;

      await tenantsTenantsPartialUpdate(tenantId, {
        ...dataToSend,
        ...mappedTenantFields,
      } as unknown as Tenant);

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
      console.error("Failed to save data:", error);
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

  const getSettingValue = useCallback(
    (key: string, defaultValue?: unknown) => {
      return SettingsRenderer.getNestedValue(settings, key, defaultValue);
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
    <div style={{ padding: "16px" }}>
      <div style={{ marginBottom: "16px" }}>
        <AutoSaveIndicator saving={saving} hasChanges={hasChanges} />
      </div>
      <Space direction="vertical" size="middle" className="w-full">
        {settingsConfig.map((category) => (
          <Card
            key={category.category}
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
                  <div style={{ padding: "4px 0" }}>
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
        ))}
      </Space>
    </div>
  );
}
