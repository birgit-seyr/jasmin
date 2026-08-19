/**
 * UI <-> Tenant model mapping for the configuration pages.
 *
 * Form keys mirror the Tenant model column names 1:1 (snake_case). A new
 * boolean/string column on ``Tenant`` surfaces in the form by simply adding
 * its key to the ConfigurationApp settings list — no edits here required.
 */

/**
 * Tenant columns backed by a Django ``FileField``/``ImageField``.
 *
 * Their READ shape is a URL string, but their WRITE shape must be an actual
 * file — so echoing a fetched tenant straight back in a JSON PATCH makes DRF
 * reject the string with "The submitted data was not a file", surfacing as a
 * 400 on a completely unrelated save (a checkbox, a phone number).
 *
 * Uploads never go through JSON: they use the multipart ``usePictureUpload``
 * hook against the same endpoint.
 *
 * **This is the single source of truth — add any new Tenant file column here.**
 * It was previously duplicated as three hand-maintained lists that had already
 * drifted apart from each other.
 */
export const TENANT_FILE_FIELDS = [
  "logo",
  "bio_logo",
  "app_icon",
  // No such column exists (the name survives only in dead frontend references);
  // kept so the strip stays a no-op rather than a behaviour change if some
  // stale payload still carries the key.
  "favicon",
] as const;

/** Copy of ``tenant`` safe to send as a JSON PATCH body. */
export function withoutTenantFileFields<T extends Record<string, unknown>>(
  tenant: T,
): Partial<T> {
  const payload: Partial<T> = { ...tenant };
  for (const field of TENANT_FILE_FIELDS) {
    delete payload[field as keyof T];
  }
  return payload;
}

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
  ...TENANT_FILE_FIELDS,
  // Read-only stamp derived from the icon + updated_at; not a setting.
  "app_icon_version",
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
