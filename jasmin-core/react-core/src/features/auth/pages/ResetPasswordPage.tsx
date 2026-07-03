import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  Card,
  Form,
  Input,
  Button,
  Alert,
  Typography,
  Space,
  Progress,
} from "antd";
import { LockOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { authPasswordResetConfirmCreate } from "@shared/api/generated/auth/auth";
import { getErrorMessage } from "@shared/utils/apiError";
import { FriendlyCaptcha } from "@shared/auth/FriendlyCaptcha";

const { Title, Text } = Typography;

interface ResetPasswordValues {
  password: string;
  password_confirm: string;
}

/** Quick client-side strength estimator. Real validation runs server-side. */
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

const ResetPasswordPage = () => {
  const { t } = useTranslation();
  const params = useParams<{ uid: string; token: string }>();
  // Snapshot the credentials once — the URL gets scrubbed below, so
  // later renders must not depend on the route params still being there.
  const [{ uid, token }] = useState(() => ({
    uid: params.uid,
    token: params.token,
  }));
  const navigate = useNavigate();
  const [form] = Form.useForm<ResetPasswordValues>();

  // The token in the URL IS the credential — scrub it from the address
  // bar so it doesn't linger in browser history, sync, or get pasted
  // along when someone shares the URL. (Refreshing after this lands on
  // a tokenless route; the user just clicks the email link again.)
  useEffect(() => {
    if (params.uid || params.token) {
      window.history.replaceState(null, "", "/reset-password");
    }
  }, [params.uid, params.token]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [pwScore, setPwScore] = useState(0);
  const [captchaSolution, setCaptchaSolution] = useState("");

  // Redirect to /login after a short success message. Driven by an effect
  // (not a bare setTimeout in the handler) so the timer is cleaned up if the
  // component unmounts first — otherwise navigate() can fire after unmount.
  useEffect(() => {
    if (!success) return;
    const timer = setTimeout(() => navigate("/login"), 1800);
    return () => clearTimeout(timer);
  }, [success, navigate]);

  const handleSubmit = async (values: ResetPasswordValues) => {
    setError(null);
    setSubmitting(true);
    try {
      await authPasswordResetConfirmCreate({
        uid: uid!,
        token: token!,
        password: values.password,
        frc_captcha_solution: captchaSolution,
      });
      setSuccess(true);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response
        ?.status;
      if (status === 429) {
        setError(
          t("auth.forgot_password.too_many_requests"),
        );
      } else {
        setError(
          getErrorMessage(
            err,
            t("auth.reset_password.invalid_link"),
          ),
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <Card className="auth-card">
        <Space direction="vertical" size="large" className="w-full">
          <div className="text-center">
            <Title level={3} style={{ marginBottom: 4 }}>
              {t("auth.reset_password.title")}
            </Title>
          </div>

          {error && <Alert type="error" message={error} showIcon />}

          {success ? (
            <Alert
              type="success"
              showIcon
              message={t("auth.reset_password.success")}
            />
          ) : (
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              autoComplete="off"
            >
              <Form.Item
                name="password"
                label={t("auth.reset_password.new_password")}
                rules={[
                  {
                    required: true,
                    message: t("auth.reset_password.password_required"),
                  },
                  {
                    min: 10,
                    message: t("auth.reset_password.password_min"),
                  },
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
                {t("auth.reset_password.password_hint")}
              </Text>

              <Form.Item
                name="password_confirm"
                label={t("auth.reset_password.confirm_password")}
                dependencies={["password"]}
                style={{ marginTop: 16 }}
                rules={[
                  {
                    required: true,
                    message: t("auth.reset_password.confirm_required"),
                  },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("password") === value) {
                        return Promise.resolve();
                      }
                      return Promise.reject(
                        new Error(
                          t("auth.reset_password.mismatch"),
                        ),
                      );
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} />
              </Form.Item>

              <FriendlyCaptcha onSolution={setCaptchaSolution} />

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  block
                  loading={submitting}
                >
                  {t("auth.reset_password.submit")}
                </Button>
              </Form.Item>
            </Form>
          )}

          <div className="text-center">
            <Link to="/login">
              {t("auth.forgot_password.back_to_login")}
            </Link>
          </div>
        </Space>
      </Card>
    </div>
  );
};

export default ResetPasswordPage;
