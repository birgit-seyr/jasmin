import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Card, Divider, Typography } from "antd";
import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useTenant } from "@hooks/index";
import { safeExternalHref } from "@shared/utils/safeUrl";

const { Title, Paragraph, Text } = Typography;

/**
 * Public legal-notice ("Impressum") page — mandatory provider
 * identification under § 5 DDG (DE, ex-§ 5 TMG) plus § 18 Abs. 2 MStV
 * for the editorial-responsibility line. Reachable unauthenticated from
 * the login footer at ``/impressum``.
 *
 * Every block is filled from the live tenant row (the anonymous
 * ``CurrentTenantSerializer`` / non-staff ``TenantNonStaffReadSerializer``
 * both expose these public identity fields), so each tenant serves its
 * own imprint from shared markup. Each section renders only when its
 * backing field is non-empty, so an e.V. / GmbH / eG all display
 * cleanly without a legal-form switch.
 */
export default function PublicLegalNoticePage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { tenant } = useTenant();

  const website = tenant?.website?.trim();
  const websiteHref = safeExternalHref(website);

  const registerType = tenant?.register_type?.trim();
  const registerNumber = tenant?.register_number?.trim();
  const registerCourt = tenant?.register_court?.trim();
  const hasRegister = Boolean(registerType || registerNumber || registerCourt);

  const legalRepresentatives = tenant?.legal_representatives?.trim();
  const supervisoryBoard = tenant?.supervisory_board?.trim();
  const contentResponsible = tenant?.content_responsible?.trim();
  const auditingAssociation = tenant?.auditing_association?.trim();
  const professionalAssociation = tenant?.professional_association?.trim();
  const organicControlNumber = tenant?.organic_control_number?.trim();
  const vatId = tenant?.uid?.trim();
  const legalForm = tenant?.legal_form?.trim();
  const extraHtml = tenant?.legal_notice_extra_html?.trim();

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
            {legalForm && (
              <>
                {legalForm}
                <br />
              </>
            )}
            {tenant?.address}
            <br />
            {tenant?.zip_code} {tenant?.city}
            <br />
            {tenant?.country}
          </Paragraph>

          {hasRegister && (
            <>
              <Divider />
              <Title level={4}>{t("impressum.register_title")}</Title>
              <Paragraph>
                {(registerType || registerNumber) && (
                  <>
                    {[registerType, registerNumber]
                      .filter(Boolean)
                      .join(": ")}
                    <br />
                  </>
                )}
                {registerCourt && (
                  <>
                    {t("impressum.register_court_label")}: {registerCourt}
                  </>
                )}
              </Paragraph>
            </>
          )}

          {legalRepresentatives && (
            <>
              <Divider />
              <Title level={4}>{t("impressum.represented_by_title")}</Title>
              <Paragraph>{legalRepresentatives}</Paragraph>
            </>
          )}

          {supervisoryBoard && (
            <>
              <Divider />
              <Title level={4}>{t("impressum.supervisory_board_title")}</Title>
              <Paragraph>{supervisoryBoard}</Paragraph>
            </>
          )}

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
                {websiteHref ? (
                  <a
                    href={websiteHref}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {website}
                  </a>
                ) : (
                  website
                )}
              </>
            )}
          </Paragraph>

          {vatId && (
            <>
              <Divider />
              <Title level={4}>{t("impressum.vat_title")}</Title>
              <Paragraph>
                {t("impressum.vat_note")}
                <br />
                {vatId}
              </Paragraph>
            </>
          )}

          {contentResponsible && (
            <>
              <Divider />
              <Title level={4}>
                {t("impressum.content_responsible_title")}
              </Title>
              <Paragraph>
                {contentResponsible} {t("impressum.responsible_for")}{" "}
                {tenant?.name}
                <br />
                {tenant?.address}
                <br />
                {tenant?.zip_code} {tenant?.city}
              </Paragraph>
            </>
          )}

          <Divider />
          <Title level={4}>{t("impressum.dispute_resolution_title")}</Title>
          <Paragraph>
            {tenant?.participates_in_dispute_resolution
              ? t("impressum.dispute_resolution_yes")
              : t("impressum.dispute_resolution_no")}
          </Paragraph>

          {auditingAssociation && (
            <>
              <Divider />
              <Title level={4}>
                {t("impressum.auditing_association_title")}
              </Title>
              <Text type="secondary">
                {t("impressum.auditing_association_note")}
              </Text>
              <Paragraph style={{ whiteSpace: "pre-line", marginTop: 8 }}>
                {auditingAssociation}
              </Paragraph>
            </>
          )}

          {organicControlNumber && (
            <>
              <Divider />
              <Title level={4}>{t("impressum.organic_control_title")}</Title>
              <Paragraph>{organicControlNumber}</Paragraph>
            </>
          )}

          {professionalAssociation && (
            <>
              <Divider />
              <Title level={4}>
                {t("impressum.professional_association_title")}
              </Title>
              <Paragraph style={{ whiteSpace: "pre-line" }}>
                {professionalAssociation}
              </Paragraph>
            </>
          )}

          {extraHtml && (
            <>
              <Divider />
              <div
                // Admin-authored content from the office Legal-notice card
                // (same trust boundary + sanitization as privacy_policy_html).
                dangerouslySetInnerHTML={{
                  __html: DOMPurify.sanitize(extraHtml),
                }}
              />
            </>
          )}

          <Divider />

          <Title level={4}>{t("impressum.liability_title")}</Title>
          <Paragraph>{t("impressum.liability_content")}</Paragraph>
          <Paragraph>{t("impressum.liability_links")}</Paragraph>
        </Typography>
      </Card>
    </div>
  );
}
