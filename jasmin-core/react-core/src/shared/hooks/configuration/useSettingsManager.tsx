import { useCallback, useEffect, useRef, useState } from "react";
import { useAutoSave } from "./useAutoSave";

interface SettingsManagerConfig {
  // The hook keys its fetch effect on ``tenant?.id`` so a tenant switch
  // triggers a re-fetch. The backend itself derives the tenant from the
  // request (subdomain → ``request.tenant``); the id here is only a
  // re-render signal, never sent in the request.
  tenant: { id: string; [key: string]: unknown } | null;
  fetchSettings: () => Promise<unknown>;
  saveSettings: (
    data: { settings: Record<string, unknown> },
  ) => Promise<unknown>;
  initialSettings?: Record<string, unknown>;
  autoSave?: boolean;
  /**
   * Debounce window for text-input changes. Single-click types
   * (``select`` / ``checkbox`` / ``switch`` / ``file``) fire at 0 ms
   * regardless — that policy lives in ``useAutoSave``.
   */
  autoSaveDelay?: number;
  /**
   * Called (and awaited) after a successful save. Pass
   * ``useTenant().refreshTenant`` so app-wide ``getSetting()`` readers
   * (pricing, PDFs, columns, packing mode, …) pick up the new values
   * instead of computing against stale ``currentTenant.settings`` until
   * a full reload.
   */
  onSaved?: () => void | Promise<void>;
}

export const useSettingsManager = ({
  tenant,
  fetchSettings: fetchSettingsFn,
  saveSettings: saveSettingsFn,
  initialSettings = {},
  autoSave = true,
  autoSaveDelay = 500,
  onSaved,
}: SettingsManagerConfig) => {
  const [settings, setSettings] = useState<Record<string, unknown>>(
    initialSettings,
  );
  const [loading, setLoading] = useState(true);

  // Stable refs for callback props to avoid re-render loops
  const fetchSettingsFnRef = useRef(fetchSettingsFn);
  fetchSettingsFnRef.current = fetchSettingsFn;
  const saveSettingsFnRef = useRef(saveSettingsFn);
  saveSettingsFnRef.current = saveSettingsFn;
  const onSavedRef = useRef(onSaved);
  onSavedRef.current = onSaved;
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const tenantRef = useRef(tenant);
  tenantRef.current = tenant;
  // `initialSettings` defaults to `{}` — a fresh object identity every render.
  // Reading via ref keeps `fetchSettings` identity tied to `tenant?.id` only;
  // listing it directly would invalidate the callback on every parent render.
  const initialSettingsRef = useRef(initialSettings);
  initialSettingsRef.current = initialSettings;

  // Save settings — uses refs to avoid depending on settings/saveSettingsFn.
  // ``useAutoSave`` owns the ``saving`` / ``hasChanges`` flags around its
  // own ``flush`` call; this body only does the actual PATCH.
  const handleSave = useCallback(async (onSuccess?: () => void) => {
    const currentTenant = tenantRef.current;
    if (!currentTenant?.id) return;

    const systemFields = [
      "id",
      "tenant",
      "valid_from",
      "valid_until",
      "created_at",
      "is_active",
    ];

    const settingsToSend = Object.fromEntries(
      Object.entries(settingsRef.current).filter(
        ([key]) => !systemFields.includes(key),
      ),
    );

    try {
      await saveSettingsFnRef.current({ settings: settingsToSend });
      // Let app-wide readers (TenantContext.getSetting()) refresh before we
      // signal success, so a subsequent navigation sees the new values.
      await onSavedRef.current?.();
      onSuccess?.();
    } catch (error) {
      console.error("Failed to save settings:", error);
      throw error;
    }
  }, []);

  const { hasChanges, saving, markChanged } = useAutoSave({
    enabled: autoSave && !loading && Boolean(tenant?.id),
    save: handleSave,
    debounceMs: autoSaveDelay,
  });

  // Fetch settings — only depends on tenant?.id (stable primitive)
  const fetchSettings = useCallback(async () => {
    const currentTenant = tenantRef.current;
    if (!currentTenant?.id) {
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const response = await fetchSettingsFnRef.current();

      let fetchedSettings: Record<string, unknown> = {};

      if (response && Array.isArray(response) && response.length > 0) {
        fetchedSettings = response[0];
      } else if (response && !Array.isArray(response)) {
        fetchedSettings = response as Record<string, unknown>;
      } else {
        fetchedSettings = initialSettingsRef.current;
      }

      setSettings(fetchedSettings);
    } catch (error) {
      console.error("Failed to fetch settings:", error);
      setSettings(initialSettingsRef.current);
    } finally {
      setLoading(false);
    }
    // `tenant?.id` IS the dep — the body reads via ref to avoid touching
    // `tenant` identity, but we still want a fresh fetch when the id changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant?.id]);

  // Handle setting change. ``fieldType`` is the renderer ``type``
  // (e.g. ``"select"``, ``"checkbox"``, ``"input"``); ``useAutoSave``
  // uses it to decide whether to fire immediately or debounce.
  const handleSettingChange = useCallback(
    (key: string, value: unknown, fieldType?: string) => {
      setSettings((prev) => {
        const newSettings: Record<string, unknown> = { ...prev };
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

  // Reset settings
  const handleReset = useCallback(() => {
    fetchSettings();
  }, [fetchSettings]);

  // Get setting value
  const getSettingValue = useCallback(
    (key: string, defaultValue?: unknown) => {
      const keys = key.split(".");
      let value: unknown = settings;

      for (const k of keys) {
        value = (value as Record<string, unknown>)?.[k];
      }

      return value !== undefined ? value : defaultValue;
    },
    [settings],
  );

  // Load settings on mount and when tenant changes
  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  return {
    settings,
    loading,
    saving,
    hasChanges,
    handleSettingChange,
    handleSave,
    handleReset,
    getSettingValue,
    fetchSettings,
  };
};
