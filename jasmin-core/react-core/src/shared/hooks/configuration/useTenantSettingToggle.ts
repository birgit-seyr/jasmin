import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { tenantsSettingsUpdateCurrentSettingsUpdate } from "@shared/api/generated/tenants/tenants";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { useTenant } from "./useTenant";

/**
 * One boolean tenant setting wired to a toggle: reads the current value
 * and persists changes (PATCH current settings → refresh the tenant so
 * ``getSetting`` reflects the new value).
 *
 * Replaces the hand-rolled
 * ``tenantsSettingsUpdateCurrentSettingsUpdate({settings:{key}}) +
 * refreshTenant()`` handlers that were copy-pasted across Offers and
 * HarvestingList — and fixes their **silent** ``console.error`` catch:
 * on failure the toggle visually snapped back with no explanation. This
 * surfaces the error via ``notify.error`` instead.
 *
 * Not for the bulk autosave paths (ConfigurationApp / SettingsPage) —
 * those batch many settings through a different debounced flow.
 */
export function useTenantSettingToggle(
  settingKey: string,
  defaultValue = false,
): {
  value: boolean;
  onChange: (checked: boolean) => Promise<void>;
  saving: boolean;
} {
  const { getSetting, refreshTenant } = useTenant();
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  const value = getSetting(settingKey, defaultValue) as boolean;

  const onChange = useCallback(
    async (checked: boolean) => {
      setSaving(true);
      try {
        await tenantsSettingsUpdateCurrentSettingsUpdate({
          settings: { [settingKey]: checked },
        });
        await refreshTenant();
      } catch (err) {
        notify.error(
          getErrorMessage(err, t("settings.save_failed")),
        );
      } finally {
        setSaving(false);
      }
    },
    [settingKey, refreshTenant, t],
  );

  return { value, onChange, saving };
}
