// The typed clients live in the em-dash-cased folder orval generates
// for each OpenAPI tag — the backend tag is ``Auth — Two-factor``,
// matching the existing convention used by ``payments-—-billing-runs``
// etc. Path looks weird but is byte-for-byte identical to the
// generated directory name.

import {
  CheckCircleOutlined,
  CopyOutlined,
  LockOutlined,
  SafetyOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  message,
  Space,
  Spin,
  Steps,
  Typography,
} from "antd";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  authTwoFactorDisableCreate,
  authTwoFactorEnrollConfirmCreate,
  authTwoFactorEnrollStartCreate,
  authTwoFactorRecoveryCodesRegenerateCreate,
  useAuthTwoFactorStatusRetrieve,
} from "@shared/api/generated/auth-—-two-factor/auth-—-two-factor";

const { Paragraph, Text } = Typography;

type Mode = "off" | "enrolling" | "on";

export default function TwoFactorPanel() {
  const { t } = useTranslation();

  // Auto-fetches on mount; ``refetch`` reloads after enrol / disable /
  // regenerate so the panel always reflects the server's view.
  const {
    data: status,
    isFetching: statusLoading,
    refetch: refetchStatus,
  } = useAuthTwoFactorStatusRetrieve();

  // Enrolment-wizard state.
  const [enrolling, setEnrolling] = useState(false);
  const [enrolStep, setEnrolStep] = useState<0 | 1 | 2>(0);
  const [provisioningUri, setProvisioningUri] = useState<string>("");
  const [qrDataUrl, setQrDataUrl] = useState<string>("");
  const [secret, setSecret] = useState<string>("");
  const [confirmCode, setConfirmCode] = useState<string>("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  // "On" state — disable + regenerate.
  const [actionCode, setActionCode] = useState<string>("");

  // Render the QR client-side when the provisioning URI is set.
  useEffect(() => {
    if (!provisioningUri) {
      setQrDataUrl("");
      return;
    }
    QRCode.toDataURL(provisioningUri, { width: 256, margin: 2 })
      .then(setQrDataUrl)
      .catch(() => message.error(t("profile.two_factor.error_render_qr")));
  }, [provisioningUri, t]);

  // ----- Enrolment wizard ------------------------------------------------

  const startEnrolment = async () => {
    try {
      const data = await authTwoFactorEnrollStartCreate();
      setProvisioningUri(data.provisioning_uri);
      setSecret(data.secret);
      setEnrolling(true);
      setEnrolStep(0);
      setConfirmCode("");
      setRecoveryCodes(null);
    } catch {
      message.error(t("profile.two_factor.error_enroll_start"));
    }
  };

  const confirmEnrolment = async () => {
    if (!confirmCode.trim()) return;
    try {
      const data = await authTwoFactorEnrollConfirmCreate({
        code: confirmCode.trim(),
      });
      setRecoveryCodes(data.recovery_codes);
      setEnrolStep(2);
      await refetchStatus();
    } catch {
      message.error(t("profile.two_factor.error_enroll_confirm"));
    }
  };

  const finishEnrolment = () => {
    setProvisioningUri("");
    setSecret("");
    setConfirmCode("");
    setRecoveryCodes(null);
    setEnrolStep(0);
    setEnrolling(false);
  };

  // ----- Disable / regenerate -------------------------------------------

  const disable = async () => {
    if (!actionCode.trim()) return;
    try {
      await authTwoFactorDisableCreate({ code: actionCode.trim() });
      setActionCode("");
      setRecoveryCodes(null);
      await refetchStatus();
      message.success(t("profile.two_factor.disabled"));
    } catch {
      message.error(t("profile.two_factor.error_disable"));
    }
  };

  const regenerate = async () => {
    if (!actionCode.trim()) return;
    try {
      const data = await authTwoFactorRecoveryCodesRegenerateCreate({
        code: actionCode.trim(),
      });
      setRecoveryCodes(data.recovery_codes);
      setActionCode("");
      await refetchStatus();
    } catch {
      message.error(t("profile.two_factor.error_regenerate"));
    }
  };

  const copyToClipboard = (text: string) => {
    void navigator.clipboard.writeText(text);
    message.success(t("common.copied"));
  };

  // ----- Render ---------------------------------------------------------

  if (statusLoading && !status) {
    return (
      <div style={{ padding: 32, textAlign: "center" }}>
        <Spin />
      </div>
    );
  }

  const mode: Mode = enrolling ? "enrolling" : status?.enrolled ? "on" : "off";

  // ----- OFF: marketing + "Enable" CTA ----------------------------------
  if (mode === "off") {
    return (
      <Card>
        <Space direction="vertical" size="middle" className="w-full">
          <Space>
            <SafetyOutlined style={{ fontSize: 22 }} />
            <Text strong>{t("profile.two_factor.status_off")}</Text>
          </Space>
          <Paragraph>{t("profile.two_factor.intro")}</Paragraph>
          <Paragraph type="secondary" style={{ fontSize: 13 }}>
            {t("profile.two_factor.recommended_apps")}
          </Paragraph>
          <Button type="primary" icon={<LockOutlined />} onClick={startEnrolment}>
            {t("profile.two_factor.enable")}
          </Button>
        </Space>
      </Card>
    );
  }

  // ----- ENROLLING: 3-step wizard ---------------------------------------
  if (mode === "enrolling") {
    return (
      <Card>
        <Steps
          current={enrolStep}
          size="small"
          items={[
            { title: t("profile.two_factor.step_scan") },
            { title: t("profile.two_factor.step_confirm") },
            { title: t("profile.two_factor.step_recovery_codes") },
          ]}
          style={{ marginBottom: 24 }}
        />

        {enrolStep === 0 && (
          <Space direction="vertical" size="middle" className="w-full">
            <Paragraph>{t("profile.two_factor.scan_instructions")}</Paragraph>
            {qrDataUrl && (
              <div style={{ textAlign: "center" }}>
                <img
                  src={qrDataUrl}
                  alt={t("profile.two_factor.qr_alt")}
                  style={{ maxWidth: 256, width: "100%" }}
                />
              </div>
            )}
            <Paragraph type="secondary" style={{ fontSize: 13 }}>
              {t("profile.two_factor.cant_scan")}
            </Paragraph>
            <Input
              readOnly
              value={secret}
              addonAfter={
                <CopyOutlined
                  onClick={() => copyToClipboard(secret)}
                  style={{ cursor: "pointer" }}
                />
              }
            />
            <Space>
              <Button onClick={finishEnrolment}>{t("common.cancel")}</Button>
              <Button type="primary" onClick={() => setEnrolStep(1)}>
                {t("profile.two_factor.added_continue")}
              </Button>
            </Space>
          </Space>
        )}

        {enrolStep === 1 && (
          <Space direction="vertical" size="middle" className="w-full">
            <Paragraph>{t("profile.two_factor.confirm_instructions")}</Paragraph>
            <Form layout="vertical" onFinish={confirmEnrolment}>
              <Form.Item label={t("profile.two_factor.code_label")} required>
                <Input
                  size="large"
                  placeholder="123456"
                  maxLength={6}
                  inputMode="numeric"
                  autoFocus
                  aria-label={t("profile.two_factor.code_label")}
                  aria-required={true}
                  value={confirmCode}
                  onChange={(e) =>
                    setConfirmCode(e.target.value.replace(/\D/g, ""))
                  }
                />
              </Form.Item>
              <Space>
                <Button onClick={() => setEnrolStep(0)}>{t("common.back")}</Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  disabled={confirmCode.length !== 6}
                >
                  {t("profile.two_factor.activate")}
                </Button>
              </Space>
            </Form>
          </Space>
        )}

        {enrolStep === 2 && recoveryCodes && (
          <Space direction="vertical" size="middle" className="w-full">
            <Alert
              type="success"
              showIcon
              icon={<CheckCircleOutlined />}
              message={t("profile.two_factor.activated")}
            />
            <Paragraph strong>
              {t("profile.two_factor.recovery_codes_title")}
            </Paragraph>
            <Paragraph>{t("profile.two_factor.recovery_codes_intro")}</Paragraph>
            <Card size="small" style={{ background: "var(--color-bg-elevated)" }}>
              <pre
                style={{
                  margin: 0,
                  fontFamily: "monospace",
                  fontSize: 14,
                  lineHeight: 1.8,
                }}
              >
                {recoveryCodes.join("\n")}
              </pre>
            </Card>
            <Space>
              <Button
                icon={<CopyOutlined />}
                onClick={() => copyToClipboard(recoveryCodes.join("\n"))}
              >
                {t("profile.two_factor.copy_codes")}
              </Button>
              <Button type="primary" onClick={finishEnrolment}>
                {t("profile.two_factor.codes_saved_done")}
              </Button>
            </Space>
          </Space>
        )}
      </Card>
    );
  }

  // ----- ON: status + manage --------------------------------------------
  const remaining = status?.recovery_codes_remaining ?? 0;
  const lowRecovery = remaining > 0 && remaining <= 3;

  return (
    <Space direction="vertical" size="middle" className="w-full">
      <Alert
        type="success"
        showIcon
        message={t("profile.two_factor.status_on")}
        description={t("profile.two_factor.status_on_description", {
          count: remaining,
        })}
      />

      {lowRecovery && (
        <Alert
          type="warning"
          showIcon
          message={t("profile.two_factor.low_recovery_codes")}
        />
      )}

      {recoveryCodes && (
        <Card size="small" style={{ background: "var(--color-bg-elevated)" }}>
          <Paragraph strong>
            {t("profile.two_factor.new_recovery_codes")}
          </Paragraph>
          <pre
            style={{
              margin: 0,
              fontFamily: "monospace",
              fontSize: 14,
              lineHeight: 1.8,
            }}
          >
            {recoveryCodes.join("\n")}
          </pre>
          <Button
            style={{ marginTop: 12 }}
            icon={<CopyOutlined />}
            onClick={() => copyToClipboard(recoveryCodes.join("\n"))}
          >
            {t("profile.two_factor.copy_codes")}
          </Button>
        </Card>
      )}

      <Card title={t("profile.two_factor.manage")} size="small">
        <Form layout="vertical">
          <Form.Item label={t("profile.two_factor.current_code_label")}>
            <Input
              placeholder="123456"
              maxLength={20}
              aria-label={t("profile.two_factor.current_code_label")}
              value={actionCode}
              onChange={(e) => setActionCode(e.target.value)}
            />
          </Form.Item>
          <Space>
            <Button onClick={regenerate} disabled={!actionCode.trim()}>
              {t("profile.two_factor.regenerate_codes")}
            </Button>
            <Button danger onClick={disable} disabled={!actionCode.trim()}>
              {t("profile.two_factor.disable")}
            </Button>
          </Space>
        </Form>
      </Card>
    </Space>
  );
}
