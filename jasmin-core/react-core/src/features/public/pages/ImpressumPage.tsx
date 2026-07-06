import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Card, Divider, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useTenant } from "@hooks/index";

const { Title, Paragraph, Text } = Typography;

/**
 * Public legal-notice ("Impressum") page — mandatory provider
 * identification under § 5 TMG (DE) / § 5 ECG (AT). Reachable
 * unauthenticated from the login footer at ``/impressum``.
 *
 * Provider name / address / contact are filled from the live tenant
 * row (the same fields the privacy-policy template uses), so each
 * tenant serves its own imprint from shared markup.
 */
export default function ImpressumPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { tenant } = useTenant();

  const website = tenant?.website?.trim();

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--color-page-bg)",
        padding: "40px 24px",
      }}
    >
      <Card style={{ maxWidth: 800, margin: "0 auto" }}>
        <Button
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(-1)}
          style={{ padding: 0, marginBottom: 16 }}
        >
          {t("common.back")}
        </Button>

        <Typography>
          <Title level={2}>{t("impressum.title")}</Title>
          <Text type="secondary">{t("impressum.tmg_note")}</Text>

          <Divider />

          <Title level={4}>{t("impressum.provider_title")}</Title>
          <Paragraph>
            <strong>{tenant?.name}</strong>
            <br />
            {tenant?.address}
            <br />
            {tenant?.zip_code} {tenant?.city}
            <br />
            {tenant?.country}
          </Paragraph>

          <Divider />

          <Title level={4}>{t("impressum.contact_title")}</Title>
          <Paragraph>
            {tenant?.phone_number && (
              <>
                {t("impressum.phone_label")}: {tenant.phone_number}
                <br />
              </>
            )}
            {tenant?.email && (
              <>
                {t("impressum.email_label")}: {tenant.email}
                <br />
              </>
            )}
            {website && (
              <>
                {t("impressum.website_label")}:{" "}
                <a href={website} target="_blank" rel="noopener noreferrer">
                  {website}
                </a>
              </>
            )}
          </Paragraph>

          <Divider />

          <Title level={4}>{t("impressum.liability_title")}</Title>
          <Paragraph>{t("impressum.liability_content")}</Paragraph>
          <Paragraph>{t("impressum.liability_links")}</Paragraph>
        </Typography>
      </Card>
    </div>
  );
}
