import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Card,
  Form,
  Input,
  Button,
  Alert,
  Typography,
  Space,
  Row,
  Col,
} from "antd";
import { LockOutlined, MailOutlined, UserOutlined } from "@ant-design/icons";
import { authRegisterCreate } from "@shared/api/generated/auth/auth";
import type { PublicRegisterRequest } from "@shared/api/generated/models";
import { getErrorMessage } from "@shared/utils/apiError";
import { passwordConfirmValidator } from "../utils/password";

const { Title, Text } = Typography;

interface RegisterValues {
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  address?: string;
  zip_code?: string;
  city?: string;
  country?: string;
  message?: string;
  password: string;
  password_confirm: string;
}

const RegisterPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form] = Form.useForm<RegisterValues>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (values: RegisterValues) => {
    setError(null);
    setSubmitting(true);
    try {
      const { password_confirm: _ignored, ...payload } = values;
      void _ignored;
      await authRegisterCreate(payload as PublicRegisterRequest);
      setSuccess(true);
      setTimeout(() => navigate("/login"), 2500);
    } catch (err: unknown) {
      setError(getErrorMessage(err, t("auth.apply.error")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page auth-page--top">
      <Card className="auth-card auth-card--wide">
        <Space direction="vertical" size="large" className="w-full">
          <div className="text-center">
            <Title level={3} style={{ marginBottom: 4 }}>
              {t("auth.apply.title")}
            </Title>
            <Text type="secondary">{t("auth.apply.subtitle")}</Text>
          </div>

          {error && <Alert type="error" message={error} showIcon />}

          {success ? (
            <Alert
              type="success"
              showIcon
              message={t("auth.apply.success_title")}
              description={t("auth.apply.success_description")}
            />
          ) : (
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              autoComplete="off"
            >
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item
                    name="first_name"
                    label={t("auth.apply.first_name")}
                    rules={[{ required: true, message: t("auth.apply.required") }]}
                  >
                    <Input prefix={<UserOutlined />} autoFocus />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="last_name"
                    label={t("auth.apply.last_name")}
                    rules={[{ required: true, message: t("auth.apply.required") }]}
                  >
                    <Input />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item
                name="email"
                label={t("auth.apply.email")}
                rules={[
                  { required: true, message: t("auth.apply.required") },
                  { type: "email", message: t("auth.apply.email_invalid") },
                ]}
              >
                <Input prefix={<MailOutlined />} />
              </Form.Item>

              <Form.Item name="phone" label={t("auth.apply.phone")}>
                <Input />
              </Form.Item>

              <Form.Item name="address" label={t("auth.apply.address")}>
                <Input />
              </Form.Item>

              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name="zip_code" label={t("auth.apply.zip")}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="city" label={t("auth.apply.city")}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="country" label={t("auth.apply.country")}>
                    <Input />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item name="message" label={t("auth.apply.message")}>
                <Input.TextArea rows={3} maxLength={2000} showCount />
              </Form.Item>

              <Form.Item
                name="password"
                label={t("auth.apply.password")}
                rules={[
                  { required: true, message: t("auth.apply.password_required") },
                  { min: 10, message: t("auth.apply.password_min") },
                ]}
              >
                <Input.Password prefix={<LockOutlined />} />
              </Form.Item>

              <Form.Item
                name="password_confirm"
                label={t("auth.apply.confirm_password")}
                dependencies={["password"]}
                rules={[
                  { required: true, message: t("auth.apply.confirm_required") },
                  ({ getFieldValue }) =>
                    passwordConfirmValidator(
                      getFieldValue,
                      t("auth.apply.mismatch"),
                    ),
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
                  {t("auth.apply.submit")}
                </Button>
              </Form.Item>
            </Form>
          )}

          <div className="text-center">
            {t("auth.registration.already_member")}{" "}
            <Link to="/login">{t("auth.registration.sign_in")}</Link>
          </div>
        </Space>
      </Card>
    </div>
  );
};

export default RegisterPage;
