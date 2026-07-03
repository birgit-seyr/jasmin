/**
 * UI <-> Tenant model mapping for the configuration pages.
 *
 * Form keys mirror the Tenant model column names 1:1 (snake_case). A new
 * boolean/string column on ``Tenant`` surfaces in the form by simply adding
 * its key to the ConfigurationApp settings list — no edits here required.
 */

// Tenant response fields that are NOT user-editable settings — never copy
// them into the form state. Anything else (booleans, scalars, simple lists)
// flows through automatically.
const TENANT_FIELDS_TO_IGNORE = new Set<string>([
  "id",
  "schema_name",
  "slug",
  "created_at",
  "updated_at",
  "created_on",
  "logo",
  "favicon",
  "bio_logo",
  "domains",
  "features",
  "is_active",
  "settings",
  "current_settings",
]);

export interface UISettings {
  currency: string;
  timezone: string;
  tenant_language: string;
  date_format: string;
  time_format: string;
  csv_format: string;
  number_locale: string;
  navigation: Record<string, unknown>;
  ai: Record<string, unknown>;
}

export const DEFAULT_UI_SETTINGS: UISettings = {
  currency: "EUR",
  timezone: "UTC",
  tenant_language: "de",
  date_format: "DD.MM.YYYY",
  time_format: "HH:mm",
  csv_format: "de",
  number_locale: "de-DE",
  navigation: {
    show_members: true,
    show_abos: true,
    show_commissioning: true,
    show_staff: true,
    show_warehouse: true,
    show_economics: true,
    show_exports: true,
    show_cultivation: true,
  },
  ai: {
    claude_enabled: false,
  },
};

export function tenantToUISettings(
  tenant: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!tenant) return { ...DEFAULT_UI_SETTINGS };

  const out: Record<string, unknown> = { ...DEFAULT_UI_SETTINGS };
  for (const [key, value] of Object.entries(tenant)) {
    if (TENANT_FIELDS_TO_IGNORE.has(key)) continue;
    if (value === undefined) continue;
    out[key] = value;
  }
  return out;
}

function uiSettingsToTenantPayload(
  ui: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(ui)) {
    if (TENANT_FIELDS_TO_IGNORE.has(key)) continue;
    out[key] = value;
  }
  return out;
}

/**
 * Build the initial form state for the ConfigurationApp's "Tenant" PATCH
 * body — every Tenant column that's user-editable, copied from the loaded
 * tenant payload. Auto-includes any new column by virtue of pass-through;
 * the only manual maintenance is :const:`TENANT_FIELDS_TO_IGNORE` above.
 */
export function tenantToSaveablePayload(
  tenant: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  if (!tenant) return {};
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(tenant)) {
    if (TENANT_FIELDS_TO_IGNORE.has(key)) continue;
    if (value === undefined) continue;
    out[key] = value;
  }
  return out;
}

/**
 * Settings stored on the versioned ``TenantSettings`` overlay (not on the
 * ``Tenant`` model itself). Saving them requires a separate call to
 * ``PUT /api/tenants/tenant-settings/update_current_settings/``.
 *
 * Add a key here whenever the ConfigurationApp exposes a field whose
 * Django home is ``TenantSettings``.
 */
export const TENANT_SETTINGS_OVERLAY_KEYS: readonly string[] = [
  "uploads_weekly_share_amount",
];

/**
 * Split the form state into the ``Tenant`` PATCH body and the
 * ``TenantSettings`` overlay body.
 */
export function splitSettingsForSave(ui: Record<string, unknown>): {
  tenantFields: Record<string, unknown>;
  settingsOverlay: Record<string, unknown>;
} {
  const settingsOverlay: Record<string, unknown> = {};
  for (const key of TENANT_SETTINGS_OVERLAY_KEYS) {
    if (key in ui) {
      settingsOverlay[key] = ui[key];
    }
  }
  // Tenant payload excludes overlay keys so we don't send them twice.
  const tenantUi = { ...ui };
  for (const key of TENANT_SETTINGS_OVERLAY_KEYS) {
    delete tenantUi[key];
  }
  return {
    tenantFields: uiSettingsToTenantPayload(tenantUi),
    settingsOverlay,
  };
}
