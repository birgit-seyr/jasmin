import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, Form, Input, Button, Alert, Typography, Space } from "antd";
import { MailOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { authPasswordResetRequestCreate } from "@shared/api/generated/auth/auth";
import { FriendlyCaptcha } from "@shared/auth/FriendlyCaptcha";

const { Title, Text } = Typography;

interface ForgotPasswordValues {
  email: string;
}

const ForgotPasswordPage = () => {
  const { t } = useTranslation();
  const [form] = Form.useForm<ForgotPasswordValues>();
  const [submitting, setSubmitting] = useState(false);
  // We always claim success on submit (server returns 200 on hit and miss)
  // to avoid leaking which addresses are registered.
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captchaSolution, setCaptchaSolution] = useState("");

  const handleSubmit = async (values: ForgotPasswordValues) => {
    setError(null);
    setSubmitting(true);
    try {
      await authPasswordResetRequestCreate({
        email: values.email,
        frc_captcha_solution: captchaSolution,
      });
      setSubmitted(true);
    } catch (err: unknown) {
      const axiosErr = err as {
        response?: { status?: number; data?: { detail?: string } };
      };
      // Throttled (429) is the only meaningful client error here.
      if (axiosErr.response?.status === 429) {
        setError(
          t("auth.forgot_password.too_many_requests"),
        );
      } else {
        setError(
          t("auth.forgot_password.generic_error"),
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
              {t("auth.forgot_password.title")}
            </Title>
            <Text type="secondary">
              {t("auth.forgot_password.subtitle")}
            </Text>
          </div>

          {error && <Alert type="error" message={error} showIcon />}

          {submitted ? (
            <Alert
              type="success"
              showIcon
              message={t("auth.forgot_password.sent_title")}
              description={t("auth.forgot_password.sent_description")}
            />
          ) : (
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              autoComplete="off"
            >
              <Form.Item
                name="email"
                label={t("auth.login_card.email")}
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
                <Input prefix={<MailOutlined />} autoFocus />
              </Form.Item>

              <FriendlyCaptcha onSolution={setCaptchaSolution} />

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  block
                  loading={submitting}
                >
                  {t("auth.forgot_password.submit")}
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

export default ForgotPasswordPage;
