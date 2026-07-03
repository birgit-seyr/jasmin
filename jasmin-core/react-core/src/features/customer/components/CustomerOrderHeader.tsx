import { MailOutlined, PhoneOutlined } from "@ant-design/icons";
import { Avatar, Card, Col, Row, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";
import type { Reseller } from "@shared/api/generated/models";
import { useAuth } from "@shared/contexts/AuthContext";
import { useLogoShape, useTenant } from "@hooks/index";

const { Title, Text } = Typography;

interface Props {
  reseller: Reseller | undefined;
  logoUrl: string | null | undefined;
}

const LOGO_SIZE = 120;

/**
 * Customer-page header card. Mirrors ``MemberDetail``'s header: logo
 * on the left, "name + email + phone" in the middle.
 *
 * Falls back to the authenticated ``JasminUser`` fields when the linked
 * ``ContactEntity`` hasn't been filled in yet (true for seed-fixture
 * customers and self-service onboardings that go through
 * ``MyCustomerDataView`` lazy provisioning). Editing happens
 * exclusively in the top-right ``UserMenu`` → "Meine Daten" — no
 * page-local edit button.
 */
export default function CustomerOrderHeader({ reseller, logoUrl }: Props) {
  const { logoShape, logoAspectRatio } = useLogoShape(logoUrl);
  const { t } = useTranslation();
  const { tenantName } = useTenant();
  const { user } = useAuth();
  const u = user as {
    first_name?: string;
    last_name?: string;
    email?: string;
  } | null;

  const isRectangle =
    logoShape === "rectangle-wide" || logoShape === "rectangle-tall";

  const displayName =
    reseller?.company_name ||
    [reseller?.first_name, reseller?.last_name].filter(Boolean).join(" ") ||
    [u?.first_name, u?.last_name].filter(Boolean).join(" ") ||
    u?.email ||
    "";

  const displayEmail = reseller?.email || u?.email;
  const displayPhone = reseller?.phone;

  return (
    <Card
      style={{
        marginBottom: "24px",
        background: "var(--gradient-primary)",
        color: "var(--color-bg-base)",
      }}
      styles={{ body: { padding: "16px" } }}
    >
      <Row align="middle" gutter={24}>
        <Col>
          {logoUrl && (isRectangle ? (
            <div
              style={{
                width:
                  logoShape === "rectangle-wide"
                    ? `${LOGO_SIZE * logoAspectRatio}px`
                    : `${LOGO_SIZE}px`,
                height:
                  logoShape === "rectangle-wide"
                    ? `${LOGO_SIZE}px`
                    : `${LOGO_SIZE / logoAspectRatio}px`,
                borderRadius: "8px",
                backgroundColor: "var(--color-bg-base)",
                padding: "8px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
              }}
            >
              <img
                src={logoUrl ?? undefined}
                alt={tenantName ?? t("common.logo")}
                style={{ width: "100%", height: "100%", objectFit: "contain" }}
              />
            </div>
          ) : (
            <Avatar
              size={64}
              src={logoUrl}
              shape="circle"
              style={{
                backgroundColor: "var(--color-bg-base)",
                padding: "8px",
              }}
              alt={tenantName ?? t("common.logo")}
            />
          ))}
        </Col>
        <Col flex="auto">
          <h1 style={{ color: "var(--color-bg-base)", marginBottom: "8px" }}>
            {displayName}
          </h1>
          <Space size="large">
            {displayEmail && (
              <Text style={{ color: "rgba(255,255,255,0.9)" }}>
                <MailOutlined /> {displayEmail}
              </Text>
            )}
            {displayPhone && (
              <Text style={{ color: "rgba(255,255,255,0.9)" }}>
                <PhoneOutlined /> {displayPhone}
              </Text>
            )}
          </Space>
        </Col>
      </Row>
    </Card>
  );
}
