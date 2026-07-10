import { LockOutlined, SafetyOutlined, UserOutlined } from "@ant-design/icons";
import { useSubscriptionTerm, useTenant } from "@hooks/index";
import { FriendlyCaptcha } from "@shared/auth/FriendlyCaptcha";
import { useAuth } from "@shared/contexts/AuthContext";
import { AboutModal } from "@shared/modals";
import { getErrorMessage } from "@shared/utils/apiError";
import {
  Alert,
  Button,
  Card,
  Flex,
  Form,
  Input,
  Space,
  Typography,
} from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

const { Title, Text } = Typography;

interface LoginFormValues {
  username: string;
  password: string;
}

const LoginPage = () => {
  const [form] = Form.useForm<LoginFormValues>();
  const [codeForm] = Form.useForm<{ code: string }>();
  const [localError, setLocalError] = useState("");

  // Two-step state. Default ``credentials``. When the server responds
  // with ``{ requires_2fa: true, challenge_token }`` we flip to
  // ``code`` and ask for the 6-digit TOTP.
  const [step, setStep] = useState<"credentials" | "code">("credentials");
  const [challengeToken, setChallengeToken] = useState<string | null>(null);

  // Friendly Captcha solution. Empty string when FC is disabled
  // (sitekey absent) or while the widget is still solving. The
  // backend ignores the field when FRIENDLY_CAPTCHA_ENABLED=False.
  const [captchaSolution, setCaptchaSolution] = useState("");
  const [aboutOpen, setAboutOpen] = useState(false);

  const { tenant, displayLogoUrl, loading: tenantLoading } = useTenant();
  const { login, verifyTwoFactor, loading, error } = useAuth();
  const { t } = useTranslation();

  // Determine if we're on super admin domain
  const isSuperAdminDomain =
    tenant?.schema_name === "public" ||
    window.location.hostname === "admin.localhost";

  // Whether to show the trial-subscription card. The flag rides on the
  // anonymous /tenants/current/ payload (CurrentTenantSerializer); show by
  // default, hide only when the tenant explicitly disabled trials.
  const allowsTrial = tenant?.allows_trial_subscriptions !== false;
  // Trial length (in deliveries/weeks) for the trial card subtitle — read from
  // the anonymous tenant payload via the shared term hook.
  const { trialDurationInDeliveries } = useSubscriptionTerm();

  const handleLogin = async (values: LoginFormValues) => {
    setLocalError("");

    try {
      const response = await login({
        email: values.username,
        password: values.password,
        frc_captcha_solution: captchaSolution,
      });
      // Narrow the LoginOrChallengeResponse union: the 2FA branch is the
      // only member carrying requires_2fa/challenge_token.
      if ("requires_2fa" in response && response.challenge_token) {
        setChallengeToken(response.challenge_token);
        setStep("code");
        return;
      }
      // Navigation is handled by the auth context on the normal path.
    } catch (err: unknown) {
      console.error("Login error:", err);
      setLocalError(getErrorMessage(err, "Login failed"));
    }
  };

  const handleVerify = async (values: { code: string }) => {
    if (!challengeToken) return;
    setLocalError("");
    try {
      await verifyTwoFactor({
        challenge_token: challengeToken,
        code: values.code.trim(),
      });
      // Navigation is handled by the auth context.
    } catch (err: unknown) {
      console.error("2FA verify error:", err);
      setLocalError(getErrorMessage(err, t("auth.two_factor.error_verify")));
    }
  };

  const handleBackToCredentials = () => {
    setStep("credentials");
    setChallengeToken(null);
    setLocalError("");
    codeForm.resetFields();
  };

  if (tenantLoading) {
    return (
      <div
        className="flex-center"
        style={{
          height: "100vh",
        }}
      >
        <div>{t("auth.login_card.loading_tenant")}</div>
      </div>
    );
  }

  // Show error from auth context or local error
  const displayError = error || localError;

  return (
    <div className="auth-page">
      <div
        className={`auth-stack ${
          isSuperAdminDomain
            ? "auth-stack--single"
            : allowsTrial
              ? "auth-stack--triple"
              : "auth-stack--double"
        }`}
      >
        {/* Header banner: the tenant logo (or name), spanning the full
            width of the card row below. */}
        {(displayLogoUrl || tenant?.name) && (
          <Card className="auth-card--shadow auth-banner">
            {displayLogoUrl ? (
              <img
                src={displayLogoUrl}
                alt={tenant?.name ?? t("common.logo")}
                width={200}
                height={75}
                // React 18 doesn't recognise the camelCase `fetchPriority`
                // prop yet (React 19); lowercase passes through as a plain
                // HTML attribute.
                {...({ fetchpriority: "high" } as Record<string, string>)}
                style={{ height: "75px", width: "auto", objectFit: "contain" }}
              />
            ) : (
              <Title level={3} style={{ margin: 0 }}>
                {tenant?.name}
              </Title>
            )}
          </Card>
        )}

        <Flex
          className="auth-cards-row"
          justify="center"
          align="start"
          wrap
          gap="large"
        >
          {/* Login Card */}

          <Card className="auth-card auth-card--narrow auth-card--shadow">
            <Space direction="vertical" size="large" className="w-full">
              <div className="text-center">
                <Title level={2}>
                  {isSuperAdminDomain
                    ? t("auth.login_card.super_admin")
                    : t("commissioning.welcome")}
                </Title>
                {tenant && (
                  <Text type="secondary">
                    {isSuperAdminDomain
                      ? t("auth.login_card.global_admin_access")
                      : `${t("auth.login_card.sign_in_to")} ${tenant.name}`}
                  </Text>
                )}
              </div>

              {displayError && (
                <Alert
                  message={displayError}
                  type="error"
                  showIcon
                  closable
                  onClose={() => setLocalError("")}
                />
              )}

              {step === "credentials" && (
                <Form
                  form={form}
                  name="login"
                  onFinish={handleLogin}
                  layout="vertical"
                  size="large"
                >
                  <Form.Item
                    name="username"
                    // label={t("auth.login_card.email")}
                    rules={[
                      {
                        required: true,
                        message: t("auth.login_card.please_enter_email"),
                      },
                      {
                        type: "email",
                        message: t("auth.login_card.please_enter_valid_email"),
                      },
                    ]}
                  >
                    <Input
                      // Visible label is commented out (placeholder-only design)
                      // — give the field an accessible name for SR users.
                      aria-label={t("auth.login_card.email")}
                      prefix={<UserOutlined />}
                      placeholder={
                        isSuperAdminDomain
                          ? `${t("auth.login_card.super_admin")} ${t("auth.login_card.email")}`
                          : t("auth.login_card.email")
                      }
                      autoComplete="username"
                    />
                  </Form.Item>

                  <Form.Item
                    name="password"
                    // label={t("auth.login_card.password")}
                    rules={[
                      {
                        required: true,
                        message: t("auth.login_card.please_enter_password"),
                      },
                    ]}
                  >
                    <Input.Password
                      aria-label={t("auth.login_card.password")}
                      prefix={<LockOutlined />}
                      placeholder={t("auth.login_card.password")}
                      autoComplete="current-password"
                    />
                  </Form.Item>

                  <div
                    style={{
                      textAlign: "right",
                      marginTop: -12,
                      marginBottom: 12,
                    }}
                  >
                    <Link to="/forgot-password" style={{ fontSize: 13 }}>
                      {t("auth.login_card.forgot_password")}
                    </Link>
                  </div>

                  <FriendlyCaptcha onSolution={setCaptchaSolution} />

                  <Form.Item>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={loading}
                      block
                    >
                      {isSuperAdminDomain
                        ? t("auth.login_card.admin_sign_in")
                        : t("auth.login_card.sign_in")}
                    </Button>
                  </Form.Item>
                </Form>
              )}

              {step === "code" && (
                <Form
                  form={codeForm}
                  name="two-factor-code"
                  onFinish={handleVerify}
                  layout="vertical"
                  size="large"
                >
                  <Text strong>{t("auth.two_factor.prompt_title")}</Text>
                  <Text type="secondary" style={{ display: "block" }}>
                    {t("auth.two_factor.prompt_subtitle")}
                  </Text>
                  <Form.Item
                    name="code"
                    label={t("auth.two_factor.code_label")}
                    style={{ marginTop: 16 }}
                    rules={[
                      {
                        required: true,
                        message: t("auth.two_factor.please_enter_code"),
                      },
                    ]}
                  >
                    <Input
                      prefix={<SafetyOutlined />}
                      placeholder="123456"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      autoFocus
                      maxLength={20}
                    />
                  </Form.Item>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t("auth.two_factor.recovery_hint")}
                  </Text>
                  <Form.Item style={{ marginTop: 16 }}>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={loading}
                      block
                    >
                      {t("auth.two_factor.verify")}
                    </Button>
                  </Form.Item>
                  <Button type="link" block onClick={handleBackToCredentials}>
                    {t("auth.two_factor.back_to_password")}
                  </Button>
                </Form>
              )}
            </Space>
          </Card>
          {/* Registration Card */}
          {!isSuperAdminDomain && (
            <Card className="auth-card auth-card--narrow auth-card--shadow">
              <Space direction="vertical" size="large" className="w-full">
                <div className="text-center">
                  <Title level={2}>{t("auth.registration.card_title")}</Title>
                  <Title level={5}>
                    {t("auth.registration.card_sub_title")}
                  </Title>
                </div>
                <div style={{ marginTop: "-1.5em" }}>
                  <ul style={{ paddingLeft: 20, color: "rgba(0,0,0,0.65)" }}>
                    <li>{t("auth.registration.overview.tell_us")}</li>
                    <li>{t("auth.registration.overview.verify_email")}</li>
                    <li>{t("auth.registration.overview.choose_shares")}</li>
                    <li>{t("auth.registration.overview.order_variation")}</li>
                  </ul>
                </div>

                <Link to="/register">
                  <Button type="primary" size="large" block disabled>
                    {t("auth.registration.start")}
                  </Button>
                </Link>
              </Space>
            </Card>
          )}
          {/* Trial Subscription Card */}
          {!isSuperAdminDomain && allowsTrial && (
            <Card className="auth-card auth-card--narrow auth-card--shadow">
              <Space direction="vertical" size="large" className="w-full">
                <div className="text-center">
                  <Title level={2}>
                    {t("auth.registration.card_title_trial")}
                  </Title>
                  {trialDurationInDeliveries != null && (
                    <Title level={5}>
                      {t("auth.registration.card_sub_title_trial", {
                        weeks: trialDurationInDeliveries,
                      })}
                    </Title>
                  )}
                </div>
                <div style={{ marginTop: "-1.5em" }}>
                  <ul
                    style={{
                      paddingLeft: 20,
                      color: "rgba(0,0,0,0.65)",
                    }}
                  >
                    <li>{t("auth.registration.overview.tell_us_trial")}</li>
                    <li>{t("auth.registration.overview.verify_email")}</li>
                    <li>
                      {t("auth.registration.overview.order_trial_variation")}
                    </li>
                  </ul>
                </div>

                <Link to="/register?trial=1">
                  <Button type="primary" size="large" block disabled>
                    {t("auth.registration.start_trial")}
                  </Button>
                </Link>
              </Space>
            </Card>
          )}
        </Flex>

        {/* Footer banner: tenant name, privacy, impressum, about — spans
            the same width as the header. */}
        <Card
          className="auth-card--shadow auth-banner"
          styles={{ body: { padding: "12px 24px" } }}
        >
          {tenant && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {isSuperAdminDomain
                ? t("auth.login_card.super_admin_portal")
                : tenant.name}
            </Text>
          )}
          <div style={{ marginTop: 4 }}>
            <Space split={<Text type="secondary">·</Text>} wrap>
              <Link to="/privacy-policy" style={{ fontSize: 12 }}>
                {t("privacy.title")}
              </Link>
              <Link to="/impressum" style={{ fontSize: 12 }}>
                {t("impressum.link")}
              </Link>
              <Text
                role="button"
                tabIndex={0}
                aria-label={t("about.open")}
                onClick={() => setAboutOpen(true)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setAboutOpen(true);
                  }
                }}
                style={{
                  fontSize: 12,
                  cursor: "pointer",
                  color: "var(--color-primary)",
                }}
              >
                2026 created by Chance
              </Text>
            </Space>
          </div>
        </Card>
      </div>
      <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} />
    </div>
  );
};

export default LoginPage;
