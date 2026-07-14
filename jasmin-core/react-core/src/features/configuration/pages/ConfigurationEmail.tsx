import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  EyeInvisibleOutlined,
  LockOutlined,
  ReloadOutlined,
  SendOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TenantEmailConfig } from "@shared/api/generated/models";
import {
  getTenantsEmailConfigListQueryKey,
  useTenantsEmailConfigList,
  useTenantsEmailConfigSavePartialUpdate,
  useTenantsEmailConfigTestCreate,
} from "@shared/api/generated/tenants/tenants";
import { LabeledSwitch } from "@shared/ui";
import { useAuth } from "@shared/contexts/AuthContext";
import { useTenant } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { blockNonNumericKeys } from "@shared/utils/numberFormat";
import {
  SettingConfig,
  SettingsCategory,
  SettingsRenderer,
} from "@features/configuration/components/SettingsRenderer";
import TestEmailModal from "@features/configuration/modals/TestEmailModal";

const { Text } = Typography;

const EMPTY_CONFIG: TenantEmailConfig = {
  smtp_host: "",
  smtp_port: 587,
  smtp_username: "",
  smtp_use_tls: true,
  from_email: "",
  from_name: "",
  reply_to_email: "",
  accounting_email: "",
  max_emails_per_hour: 1000,
  is_active: true,
};

export default function ConfigurationEmail() {
  const [config, setConfig] = useState<TenantEmailConfig>(EMPTY_CONFIG);
  const [hasChanges, setHasChanges] = useState(false);
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [credentialFields, setCredentialFields] = useState<{
    smtp_password?: string;
  }>({});

  const { t } = useTranslation();
  const { tenant } = useTenant();
  const { user } = useAuth();
  const queryClient = useQueryClient();

  // The backend only accepts test sends to the requesting user's own
  // email or the (admin-controlled) tenant contact address — the
  // office-writable sender / reply-to are deliberately not allowed
  // (no spam relay via a compromised office account). Offer exactly
  // those two.
  const allowedTestRecipients = useMemo(() => {
    const candidates = [
      (user as { email?: string } | null)?.email,
      tenant?.email as string | undefined,
    ];
    return [
      ...new Set(
        candidates
          .filter((address): address is string => Boolean(address))
          .map((address) => address.trim())
          .filter(Boolean),
      ),
    ];
  }, [user, tenant]);

  // Fetch config via generated query hook
  const { data: configData, isLoading: loading } = useTenantsEmailConfigList({
    query: {
      select: (data) => {
        // Backend returns a single object, orval types it as array
        const raw = data as unknown;
        return (Array.isArray(raw) ? raw[0] : raw) as TenantEmailConfig;
      },
    },
  });

  // Save mutation via generated hook
  const { mutateAsync: saveConfig, isPending: saving } =
    useTenantsEmailConfigSavePartialUpdate({
      mutation: {
        onSuccess: () => {
          notify.success(t("email_config.saved"));
          setCredentialFields({});
          setHasChanges(false);
          queryClient.invalidateQueries({
            queryKey: getTenantsEmailConfigListQueryKey(),
          });
        },
        onError: () => {
          notify.error(t("email_config.save_error"));
        },
      },
    });

  // Sync query data into local state — but never clobber an in-progress edit.
  // With the global staleTime:0 + refetchOnWindowFocus, a focus-refetch
  // returning changed server data would otherwise overwrite unsaved fields.
  // ``hasChanges``/``saving`` are intentionally omitted from the deps so merely
  // toggling them never re-seeds over a fresh draft (matches the
  // ConfigurationGeneral sibling).
  useEffect(() => {
    if (hasChanges || saving) return;
    if (configData) {
      setConfig(configData);
      setHasChanges(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configData]);

  // Track changes
  const updateField = useCallback((field: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setHasChanges(true);
  }, []);

  const updateCredential = useCallback(
    (field: "smtp_password", value: string) => {
      setCredentialFields((prev) => ({ ...prev, [field]: value }));
      setHasChanges(true);
    },
    [],
  );

  // Save
  const handleSave = useCallback(async () => {
    const payload: TenantEmailConfig = {
      smtp_host: config.smtp_host,
      smtp_port: config.smtp_port,
      smtp_username: config.smtp_username,
      smtp_use_tls: config.smtp_use_tls,
      from_email: config.from_email!,
      from_name: config.from_name!,
      reply_to_email: config.reply_to_email || "",
      accounting_email: config.accounting_email || "",
      max_emails_per_hour: config.max_emails_per_hour,
      is_active: config.is_active,
    };

    if (credentialFields.smtp_password) {
      payload.smtp_password = credentialFields.smtp_password;
    }

    await saveConfig({ data: payload });
  }, [config, credentialFields, saveConfig]);

  // Reset
  const handleReset = useCallback(() => {
    if (configData) {
      setConfig(configData);
    }
    setCredentialFields({});
    setHasChanges(false);
  }, [configData]);

  // Test email mutation via generated hook
  const { mutateAsync: sendTestEmail, isPending: sendingTest } =
    useTenantsEmailConfigTestCreate({
      mutation: {
        onSuccess: () => {
          notify.success(t("email_config.test_sent"));
          setTestModalOpen(false);
          queryClient.invalidateQueries({
            queryKey: getTenantsEmailConfigListQueryKey(),
          });
        },
        onError: (error) => {
          notify.error(getErrorMessage(error, t("email_config.test_error")));
        },
      },
    });

  // Test email
  const handleTestEmail = useCallback(
    async (toEmail: string) => {
      await sendTestEmail({ data: { to_email: toEmail } });
    },
    [sendTestEmail],
  );

  // Declarative config for the simple sections (mirrors ConfigurationMembers.tsx).
  // Status and SMTP Credentials remain bespoke below — they need
  // encrypted write-only fields and custom switch labels.
  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "sender",
        title: t("email_config.sender_title"),
        settings: [
          {
            key: "from_email",
            label: t("email_config.from_email"),
            type: "input",
            required: true,
            defaultValue: "noreply@yourfarm.com",
          },
          {
            key: "from_name",
            label: t("email_config.from_name"),
            type: "input",
            required: true,
            defaultValue: tenant?.name || "Your Farm",
          },
          {
            key: "reply_to_email",
            label: t("email_config.reply_to"),
            type: "input",
            defaultValue: t("email_config.reply_to_placeholder"),
          },
        ],
      },
      {
        category: "rate_limit",
        title: t("email_config.rate_limit_title"),
        settings: [
          {
            key: "max_emails_per_hour",
            label: t("email_config.max_per_hour"),
            type: "number",
            min: 1,
            max: 100000,
          },
        ],
      },
      {
        category: "invoice",
        title: t("email_config.invoice_settings_title"),
        settings: [
          {
            key: "accounting_email",
            label: t("email_config.accounting_email"),
            type: "input",
            defaultValue: t("email_config.accounting_email_placeholder"),
          },
        ],
      },
    ],
    [t, tenant?.name],
  );

  const renderDeclarativeCategory = useCallback(
    (category: SettingsCategory) => (
      <Card
        key={category.category}
        title={category.title}
        className="settings-card-header page-narrow"
        styles={{ body: { padding: "16px" } }}
      >
        <Row gutter={[16, 16]}>
          {category.settings.map((setting: SettingConfig) => (
            <Col
              span={SettingsRenderer.getColumnSpan(setting)}
              key={setting.key}
            >
              <div>
                {SettingsRenderer.renderInput(
                  setting,
                  (config as unknown as Record<string, unknown>)[setting.key],
                  (newValue) => updateField(setting.key, newValue),
                )}
                {SettingsRenderer.renderDescription(setting)}
              </div>
            </Col>
          ))}
        </Row>
      </Card>
    ),
    [config, updateField],
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
      <h1>{t("configuration.email")}</h1>
      {/* Action buttons */}
      <Card
        className="page-narrow"
        style={{
          textAlign: "center",
          marginBottom: "1em",
        }}
      >
        <Space size="middle">
          <Button
            type="primary"
            onClick={handleSave}
            loading={saving}
            disabled={!hasChanges}
          >
            {t("settings.save")}
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={handleReset}
            disabled={!hasChanges || saving}
          >
            {t("settings.reset")}
          </Button>
          <Button
            icon={<SendOutlined />}
            onClick={() => setTestModalOpen(true)}
            disabled={!config.from_email || hasChanges}
          >
            {t("email_config.send_test")}
          </Button>
        </Space>
        {hasChanges && (
          <div style={{ marginTop: "8px" }}>
            <Text type="warning">{t("settings.unsaved_changes")}</Text>
          </div>
        )}
      </Card>

      {/* Verification status */}
      {config.from_email && (
        <Alert
          className="page-narrow"
          style={{ marginBottom: "16px" }}
          type={config.is_verified ? "success" : "warning"}
          showIcon
          icon={
            config.is_verified ? (
              <CheckCircleOutlined />
            ) : (
              <ExclamationCircleOutlined />
            )
          }
          message={
            config.is_verified
              ? t("email_config.verified")
              : t("email_config.not_verified")
          }
        />
      )}

      <Space direction="vertical" size="middle" className="w-full">
        {/* Status */}
        <Card
          title={t("email_config.status_title")}
          className="settings-card-header page-narrow"
          styles={{ body: { padding: "16px" } }}
        >
          <LabeledSwitch
            value={config.is_active ?? true}
            onChange={(v: boolean) => updateField("is_active", v)}
            label={
              <>
                {config.is_active ? t("common.active") : t("common.inactive")}
                {config.is_verified && (
                  <Tag
                    color="green"
                    icon={<CheckCircleOutlined />}
                    style={{ marginLeft: 12 }}
                  >
                    {t("email_config.verified_tag")}
                  </Tag>
                )}
              </>
            }
          />
        </Card>

        {/* Sender Identity (declarative) */}
        {renderDeclarativeCategory(settingsConfig[0])}

        {/* SMTP Credentials */}
        <Card
          title={
            <Space>
              <LockOutlined />
              {t("email_config.smtp_credentials_title")}
            </Space>
          }
          className="settings-card-header page-narrow"
          styles={{ body: { padding: "16px" } }}
        >
          <Alert
            type="info"
            showIcon
            icon={<EyeInvisibleOutlined />}
            message={t("email_config.credentials_info")}
            style={{ marginBottom: 16 }}
          />

          <Row gutter={[16, 16]}>
            <Col span={16}>
              <Text strong>{t("email_config.smtp_host")}</Text>
              <Input
                value={config.smtp_host ?? ""}
                onChange={(e) => updateField("smtp_host", e.target.value)}
                placeholder="smtp.gmail.com"
                style={{ marginTop: 4 }}
              />
            </Col>
            <Col span={8}>
              <Text strong>{t("email_config.smtp_port")}</Text>
              <InputNumber
                value={config.smtp_port}
                onChange={(v) => updateField("smtp_port", v)}
                style={{ width: "100%", marginTop: 4 }}
                min={1}
                max={65535}
                precision={0}
                decimalSeparator="."
                onKeyDown={blockNonNumericKeys({
                  allowDecimal: false,
                  decimalChar: ".",
                })}
              />
            </Col>
            <Col span={12}>
              <Text strong>{t("email_config.smtp_username")}</Text>
              <Input
                value={config.smtp_username ?? ""}
                onChange={(e) => updateField("smtp_username", e.target.value)}
                placeholder="user@gmail.com"
                style={{ marginTop: 4 }}
              />
            </Col>
            <Col span={12}>
              <Text strong>{t("email_config.smtp_password")}</Text>
              <Input.Password
                value={credentialFields.smtp_password ?? ""}
                onChange={(e) =>
                  updateCredential("smtp_password", e.target.value)
                }
                placeholder={
                  config.has_smtp_password
                    ? "••••••••  (saved)"
                    : t("email_config.enter_password")
                }
                style={{ marginTop: 4 }}
              />
              {config.has_smtp_password && !credentialFields.smtp_password && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t("email_config.password_set")}
                </Text>
              )}
            </Col>
            <Col span={12}>
              <div style={{ marginTop: 8 }}>
                <LabeledSwitch
                  value={config.smtp_use_tls ?? true}
                  onChange={(v: boolean) => updateField("smtp_use_tls", v)}
                  label={t("email_config.use_tls")}
                />
              </div>
            </Col>
          </Row>
        </Card>

        {/* Rate Limiting (declarative) */}
        {renderDeclarativeCategory(settingsConfig[1])}

        {/* Invoice Settings (declarative) */}
        {renderDeclarativeCategory(settingsConfig[2])}
      </Space>

      {/* Test Email Modal */}
      <TestEmailModal
        open={testModalOpen}
        onCancel={() => setTestModalOpen(false)}
        onSend={handleTestEmail}
        sending={sendingTest}
        allowedEmails={allowedTestRecipients}
        defaultEmail={(tenant?.email as string) || allowedTestRecipients[0]}
      />
    </div>
  );
}
