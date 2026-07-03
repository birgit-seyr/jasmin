import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Card,
  Form,
  Input,
  Button,
  Alert,
  Typography,
  Space,
  Spin,
  Progress,
} from "antd";
import { LockOutlined } from "@ant-design/icons";
import {
  authInvitationsAcceptCreate,
  authInvitationsRetrieve,
} from "@shared/api/generated/auth/auth";
import type { InvitationVerifyResponse } from "@shared/api/generated/models";
import { getErrorMessage } from "@shared/utils/apiError";

const { Title, Text } = Typography;

interface SetPasswordValues {
  password: string;
  password_confirm: string;
}

/**
 * Quick client-side strength estimator.
 *
 * Real validation happens on the server (zxcvbn ≥ 3) — this is just a UX
 * affordance to nudge users towards a passing password without round-tripping.
 */
function clientPasswordScore(pw: string): number {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (pw.length >= 16) score++;
  return Math.min(score, 4);
}

const SetPasswordPage = () => {
  const { t } = useTranslation();
  const params = useParams<{ token: string }>();
  // Snapshot the token once — the URL gets scrubbed below, so later
  // renders must not depend on the route param still being there.
  const [token] = useState(() => params.token);
  const navigate = useNavigate();
  const [form] = Form.useForm<SetPasswordValues>();

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [info, setInfo] = useState<InvitationVerifyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [pwScore, setPwScore] = useState(0);

  // The invitation token in the URL IS the credential — scrub it from
  // the address bar so it doesn't linger in browser history or sync.
  useEffect(() => {
    if (params.token) {
      window.history.replaceState(null, "", "/set-password");
    }
  }, [params.token]);

  useEffect(() => {
    if (!token) {
      setError(t("auth.set_password.missing_token"));
      setLoading(false);
      return;
    }
    authInvitationsRetrieve(token)
      .then(setInfo)
      .catch(() => setError(t("auth.set_password.invalid_link")))
      .finally(() => setLoading(false));
  }, [token, t]);

  // Redirect to /login after a short success message. Driven by an effect
  // (not a bare setTimeout in the handler) so the timer is cleaned up if the
  // component unmounts first — otherwise navigate() can fire after unmount.
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => navigate("/login"), 1800);
    return () => clearTimeout(timer);
  }, [success, navigate]);

  const handleSubmit = async (values: SetPasswordValues) => {
    setError(null);
    setSubmitting(true);
    try {
      await authInvitationsAcceptCreate({
        token: token!,
        password: values.password,
      });
      setSuccess(true);
    } catch (err: unknown) {
      setError(getErrorMessage(err, t("auth.set_password.error")));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="auth-page">
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div className="auth-page">
      <Card className="auth-card">
        <Space direction="vertical" size="large" className="w-full">
          <div className="text-center">
            <Title level={3} style={{ marginBottom: 4 }}>
              {t("auth.set_password.welcome")}
              {info?.first_name ? `, ${info.first_name}` : ""}!
            </Title>
            {info?.tenant_name && (
              <Text type="secondary">
                {t("auth.set_password.invited_to", {
                  tenant: info.tenant_name,
                })}
              </Text>
            )}
          </div>

          {error && <Alert type="error" message={error} showIcon />}

          {success ? (
            <Alert
              type="success"
              showIcon
              message={t("auth.set_password.success")}
            />
          ) : info ? (
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              autoComplete="off"
            >
              <Form.Item label={t("auth.set_password.email")}>
                <Input
                  value={info.email}
                  disabled
                  aria-label={t("auth.set_password.email")}
                />
              </Form.Item>

              <Form.Item
                name="password"
                label={t("auth.set_password.choose_password")}
                rules={[
                  {
                    required: true,
                    message: t("auth.set_password.password_required"),
                  },
                  { min: 10, message: t("auth.set_password.password_min") },
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined />}
                  onChange={(e) =>
                    setPwScore(clientPasswordScore(e.target.value))
                  }
                  autoFocus
                />
              </Form.Item>

              <Progress
                percent={(pwScore / 4) * 100}
                showInfo={false}
                strokeColor={
                  pwScore >= 3
                    ? "var(--color-success)"
                    : pwScore >= 2
                      ? "var(--color-warning)"
                      : "var(--color-error)"
                }
                style={{ marginTop: -16, marginBottom: 8 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t("auth.set_password.password_hint")}
              </Text>

              <Form.Item
                name="password_confirm"
                label={t("auth.set_password.confirm_password")}
                dependencies={["password"]}
                style={{ marginTop: 16 }}
                rules={[
                  {
                    required: true,
                    message: t("auth.set_password.confirm_required"),
                  },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("password") === value) {
                        return Promise.resolve();
                      }
                      return Promise.reject(
                        new Error(t("auth.set_password.mismatch")),
                      );
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  block
                  loading={submitting}
                >
                  {t("auth.set_password.submit")}
                </Button>
              </Form.Item>
            </Form>
          ) : null}

          <div className="text-center">
            <Link to="/login">{t("auth.forgot_password.back_to_login")}</Link>
          </div>
        </Space>
      </Card>
    </div>
  );
};

export default SetPasswordPage;
