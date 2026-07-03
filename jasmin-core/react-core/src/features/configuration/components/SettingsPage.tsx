import { EditOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  Flex,
  InputNumber,
  Row,
  Space,
  Spin,
  Typography,
} from "antd";
import { ReactNode, useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  tenantsSettingsList,
  tenantsSettingsUpdateCurrentSettingsUpdate,
  useTenantsSettingsLockedSettingsRetrieve,
} from "@shared/api/generated/tenants/tenants";
import RichTextEditorModal from "@shared/modals/RichTextEditorModal";
import { AutoSaveIndicator } from "@shared/ui";
import { blockNonNumericKeys } from "@shared/utils/numberFormat";
import {
  useNumberFormat,
  useSettingsManager,
  useTenant,
} from "@hooks/index";
import {
  SettingConfig,
  SettingsCategory,
  SettingsRenderer,
} from "./SettingsRenderer";

const { Text } = Typography;

interface RichTextModalState {
  visible: boolean;
  key: string | null;
  title: string;
  value: string;
  placeholder: string;
  maxLines?: number | null;
  maxCharacters?: number | null;
  maxCharsPerLine?: number | null;
}

const EMPTY_MODAL: RichTextModalState = {
  visible: false,
  key: null,
  title: "",
  value: "",
  placeholder: "",
};

interface SettingsPageProps {
  /** Setting categories (label + inputs grouped under cards). */
  settingsConfig: SettingsCategory[];
  /** Max width for each card. Defaults to 800. Pass 900 for richtext-heavy pages. */
  cardMaxWidth?: number | string;
  /** When true, fetches locked settings from the backend and disables matching keys. */
  withLockedSettings?: boolean;
  /** Optional override for the locked tooltip text. */
  lockedTooltip?: string;
  /**
   * Optional interceptor invoked just before a setting changes.
   * Use it to enforce mutually exclusive settings, etc.
   * Called with the current setSetting function so the interceptor can apply
   * additional changes (e.g. uncheck the opposite).
   */
  onBeforeSettingChange?: (
    key: string,
    value: unknown,
    setSetting: (key: string, value: unknown) => void,
  ) => void;
  /** Slot rendered above the cards (inside the page). Can be a render-prop to access settings helpers. */
  extraBefore?: ReactNode | ((helpers: SettingsHelpers) => ReactNode);
  /** Slot rendered below the cards (inside the page). Can be a render-prop to access settings helpers. */
  extraAfter?: ReactNode | ((helpers: SettingsHelpers) => ReactNode);
}

export interface SettingsHelpers {
  getSettingValue: (key: string, defaultValue?: unknown) => unknown;
  /**
   * Push a change into ``useSettingsManager``. ``fieldType`` is the
   * renderer's ``type`` string — passing it lets the autosave hook
   * choose between immediate (``select`` / ``checkbox`` / ``switch`` /
   * ``file``) and debounced (text input) PATCHes.
   */
  handleSettingChange: (
    key: string,
    value: unknown,
    fieldType?: string,
  ) => void;
  /** Render a single setting (input + description) using the same logic as the cards. */
  renderSetting: (setting: SettingConfig) => ReactNode;
}

/**
 * Standard settings page: AutoSave indicator + spinner + Card/Row/Col loop
 * over a `settingsConfig`. Handles `richtext`, `tiers`, plain inputs,
 * description-below-input, and optional locked settings.
 *
 * Pages that just render a `useSettingsManager`-backed list of settings
 * should use this. Use `extraBefore` / `extraAfter` for custom blocks.
 */
export default function SettingsPage({
  settingsConfig,
  cardMaxWidth = 800,
  withLockedSettings = false,
  lockedTooltip,
  onBeforeSettingChange,
  extraBefore,
  extraAfter,
}: SettingsPageProps) {
  const { t } = useTranslation();
  const { tenant, refreshTenant } = useTenant();
  const { separators } = useNumberFormat();

  const {
    loading,
    saving,
    hasChanges,
    handleSettingChange: rawHandleSettingChange,
    getSettingValue,
  } = useSettingsManager({
    tenant: tenant as { id: string; [key: string]: unknown } | null,
    fetchSettings: () => tenantsSettingsList(),
    saveSettings: (data) => tenantsSettingsUpdateCurrentSettingsUpdate(data),
    initialSettings: {},
    onSaved: refreshTenant,
  });

  const handleSettingChange = useCallback(
    (key: string, value: unknown, fieldType?: string) => {
      if (onBeforeSettingChange) {
        onBeforeSettingChange(key, value, rawHandleSettingChange);
      }
      rawHandleSettingChange(key, value, fieldType);
    },
    [onBeforeSettingChange, rawHandleSettingChange],
  );

  // Locked settings (optional). React Query gates the call on
  // ``withLockedSettings`` + a tenant being present; a failure resolves
  // to an empty list via the select fallback so the page stays usable.
  const { data: lockedSettings = [] } = useTenantsSettingsLockedSettingsRetrieve(
    {
      query: {
        enabled: !!withLockedSettings && !!tenant?.id,
        select: (res) => res.locked_settings ?? [],
      },
    },
  );

  const resolvedLockedTooltip =
    lockedTooltip ??
    t("tooltip.locked_setting_tooltip");

  const resolvedConfig = useMemo<SettingsCategory[]>(() => {
    if (!withLockedSettings || lockedSettings.length === 0) {
      return settingsConfig;
    }
    return settingsConfig.map((category) => ({
      ...category,
      settings: category.settings.map((s) =>
        lockedSettings.includes(s.key)
          ? { ...s, disabled: true, disabledTooltip: resolvedLockedTooltip }
          : s,
      ),
    }));
  }, [
    settingsConfig,
    withLockedSettings,
    lockedSettings,
    resolvedLockedTooltip,
  ]);

  // Rich text editor modal
  const [richTextModal, setRichTextModal] =
    useState<RichTextModalState>(EMPTY_MODAL);
  // Bumped each time the editor opens. Used as the React ``key`` on
  // ``<RichTextEditorModal />`` below so every open creates a fresh
  // component instance — its ``useState(value || "")`` then
  // initialises with the value just passed in. Without this, the modal
  // mounts once at page load with ``value=""``, the state sticks at
  // ``""``, and the first open after that race-conditions a
  // ``setContent`` update against ReactQuill's async mount lifecycle.
  // Subsequent opens used to "work" only because ReactQuill happened
  // to be mounted from the previous attempt and picked up the new
  // value prop the second time around.
  const [richTextModalNonce, setRichTextModalNonce] = useState(0);

  const openRichTextEditor = useCallback(
    (setting: SettingConfig, currentValue: string) => {
      setRichTextModal({
        visible: true,
        key: setting.key,
        title: setting.label,
        value: currentValue || "",
        placeholder: setting.placeholderKey ? t(setting.placeholderKey) : "",
        maxLines: setting.maxLines,
        maxCharacters: setting.maxCharacters,
        maxCharsPerLine: setting.maxCharsPerLine,
      });
      setRichTextModalNonce((n) => n + 1);
    },
    [t],
  );

  const handleRichTextSave = useCallback(
    (content: string) => {
      if (richTextModal.key) {
        handleSettingChange(richTextModal.key, content);
      }
      setRichTextModal(EMPTY_MODAL);
    },
    [richTextModal.key, handleSettingChange],
  );

  // Render an individual setting (handles richtext + tiers + delegates to renderer)
  const renderSetting = useCallback(
    (setting: SettingConfig) => {
      const value = getSettingValue(setting.key, setting.defaultValue);

      if (setting.type === "richtext") {
        return (
          <div>
            <div
              className="flex-between"
              style={{
                marginBottom: "8px",
              }}
            >
              <Text strong>{setting.label}</Text>
              <Button
                icon={<EditOutlined />}
                onClick={() => openRichTextEditor(setting, value as string)}
                size="small"
                disabled={setting.disabled}
              >
                {t("common.edit")}
              </Button>
            </div>
            {SettingsRenderer.renderDescription(setting)}
          </div>
        );
      }

      if (setting.type === "tiers") {
        return (
          <TiersField
            setting={setting}
            value={value}
            onChange={(v) => handleSettingChange(setting.key, v, setting.type)}
          />
        );
      }

      return (
        <div>
          {SettingsRenderer.renderInput(
            setting,
            value,
            (newValue) =>
              handleSettingChange(setting.key, newValue, setting.type),
            { decimalChar: separators.decimalChar },
          )}
          {SettingsRenderer.renderDescription(setting)}
        </div>
      );
    },
    [
      getSettingValue,
      handleSettingChange,
      openRichTextEditor,
      t,
      separators.decimalChar,
    ],
  );

  if (loading) {
    return (
      <div className="loading-placeholder">
        <Spin size="large" />
      </div>
    );
  }

  const helpers: SettingsHelpers = {
    getSettingValue,
    handleSettingChange,
    renderSetting,
  };
  const resolvedExtraBefore =
    typeof extraBefore === "function" ? extraBefore(helpers) : extraBefore;
  const resolvedExtraAfter =
    typeof extraAfter === "function" ? extraAfter(helpers) : extraAfter;

  return (
    <div style={{ padding: "16px" }}>
      <div style={{ marginBottom: "16px" }}>
        <AutoSaveIndicator saving={saving} hasChanges={hasChanges} />
      </div>
      <Space direction="vertical" size="middle" className="w-full">
        {resolvedExtraBefore}
        {resolvedConfig.map((category) => (
          <Card
            key={category.category}
            title={category.title}
            style={{ width: "100%", maxWidth: cardMaxWidth }}
            styles={{ body: { padding: "16px" } }}
            className="settings-card-header"
          >
            {category.description && (
              <div style={{ marginBottom: "12px" }}>
                <Text type="secondary">{category.description}</Text>
              </div>
            )}
            <Row gutter={[12, 12]}>
              {category.settings
                // Conditional visibility — settings can opt in via
                // ``visibleIf(getSettingValue)`` to hide themselves
                // when a related toggle is off (e.g. the "number of
                // jokers" input hides until ``uses_jokers`` is on).
                .filter(
                  (setting) =>
                    !setting.visibleIf || setting.visibleIf(getSettingValue),
                )
                .map((setting) => (
                  <Col
                    span={SettingsRenderer.getColumnSpan(setting)}
                    key={setting.key}
                  >
                    <div style={{ padding: "4px 0" }}>
                      {renderSetting(setting)}
                    </div>
                  </Col>
                ))}
            </Row>
          </Card>
        ))}
        {resolvedExtraAfter}
      </Space>

      <RichTextEditorModal
        key={richTextModalNonce}
        visible={richTextModal.visible}
        onClose={() => setRichTextModal(EMPTY_MODAL)}
        value={richTextModal.value}
        onSave={handleRichTextSave}
        title={richTextModal.title}
        placeholder={richTextModal.placeholder}
        maxLines={richTextModal.maxLines}
        maxCharacters={richTextModal.maxCharacters}
        maxCharsPerLine={richTextModal.maxCharsPerLine}
      />
    </div>
  );
}

// ---------- Tiers field (extracted from ConfigurationResellerDocuments) ----------

interface TiersFieldProps {
  setting: SettingConfig;
  value: unknown;
  onChange: (value: (number | null)[]) => void;
}

function TiersField({ setting, value, onChange }: TiersFieldProps) {
  const { t } = useTranslation();
  const tiers = Array.isArray(value) ? (value as (number | null)[]) : [];
  const tierFrom = t("settings.reseller.offer_tier_from");
  const tierPU = t("settings.reseller.offer_tier_pu");
  const tierLabel = t("settings.reseller.offer_tier_label");

  // Stable React keys, one per tier, kept in a ref so the saved payload
  // stays a plain ``(number | null)[]``. Index-based keys made a removed
  // middle tier reuse the wrong DOM node; these ids travel with the tier
  // across add/remove/edit. The ref length is reconciled to the current
  // tiers length on every render (handles external value changes too).
  const tierKeys = useRef<number[]>([]);
  const nextTierKey = useRef(0);
  while (tierKeys.current.length < tiers.length) {
    tierKeys.current.push(nextTierKey.current++);
  }
  if (tierKeys.current.length > tiers.length) {
    tierKeys.current.length = tiers.length;
  }

  const updateTier = (index: number, newVal: number | null) => {
    const updated = [...tiers];
    updated[index] = newVal;
    onChange(updated);
  };

  const addTier = () => {
    if (tiers.length < 3) {
      tierKeys.current.push(nextTierKey.current++);
      onChange([...tiers, null]);
    }
  };

  const removeTier = (index: number) => {
    tierKeys.current.splice(index, 1);
    onChange(tiers.filter((_, i) => i !== index));
  };

  return (
    <div>
      <Text strong>{setting.label}</Text>
      {setting.description && (
        <div style={{ marginTop: "4px", marginBottom: "8px" }}>
          <Text type="secondary" style={{ fontSize: "12px" }}>
            {setting.description}
          </Text>
        </div>
      )}
      <Flex vertical gap="8px">
        {tiers.map((tier, index) => (
          <div
            key={tierKeys.current[index]}
            className="flex-center-y gap-8"
          >
            <Text style={{ minWidth: "60px" }}>
              {tierLabel} {index + 1}:
            </Text>
            <Text>{tierFrom}</Text>
            <InputNumber
              min={1}
              value={tier}
              onChange={(val) => updateTier(index, val)}
              style={{ width: "100px" }}
              disabled={index === 0}
              decimalSeparator="."
              onKeyDown={blockNonNumericKeys({
                allowDecimal: true,
                decimalChar: ".",
              })}
            />
            <Text>{tierPU}</Text>
            {index > 0 && (
              <Button
                type="link"
                danger
                size="small"
                onClick={() => removeTier(index)}
              >
                {t("common.remove")}
              </Button>
            )}
          </div>
        ))}
        {tiers.length === 0 && (
          <Button
            type="dashed"
            size="small"
            onClick={() => onChange([1])}
            style={{ width: "fit-content" }}
          >
            {t("common.add")} {tierLabel}
          </Button>
        )}
        {tiers.length > 0 && tiers.length < 3 && (
          <Button
            type="dashed"
            size="small"
            onClick={addTier}
            style={{ width: "fit-content" }}
          >
            + {tierLabel} {tiers.length + 1}
          </Button>
        )}
      </Flex>
    </div>
  );
}
