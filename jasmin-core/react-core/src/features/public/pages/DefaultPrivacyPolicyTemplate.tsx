import { Divider, Typography } from "antd";
import { useTranslation } from "react-i18next";

import type { Tenant } from "@shared/api/generated/models";

const { Title, Paragraph, Text } = Typography;

type TenantInfo = Pick<
  Tenant,
  "name" | "address" | "zip_code" | "city" | "country" | "email" | "phone_number"
>;

interface Props {
  tenant: TenantInfo | null | undefined;
}

/**
 * Generic GDPR Art. 13/14 privacy-policy template, shared by:
 *
 *   - the public ``/privacy`` route (fallback when no per-tenant
 *     override is set on ``Tenant.privacy_policy_html``)
 *   - the office-side ``Vorschau Standardvorlage`` preview modal in
 *     ``PrivacyPolicyEditorCard``
 *
 * Org name / address / contact are filled from the live tenant row so
 * the preview matches exactly what an anonymous visitor would see.
 */
export default function DefaultPrivacyPolicyTemplate({ tenant }: Props) {
  const { t } = useTranslation();

  return (
    <Typography>
      <Title level={2}>{t("privacy.title")}</Title>
      <Text type="secondary">{t("privacy.last_updated")}: 2026-04-09</Text>

      <Divider />

      <Title level={4}>{t("privacy.controller_title")}</Title>
      <Paragraph>{t("privacy.controller_text")}</Paragraph>
      <Paragraph>
        <strong>{tenant?.name}</strong>
        <br />
        {tenant?.address}
        <br />
        {tenant?.zip_code} {tenant?.city}
        <br />
        {tenant?.country}
        <br />
        {tenant?.email}
        <br />
        {tenant?.phone_number}
      </Paragraph>

      <Divider />

      <Title level={4}>{t("privacy.data_collected_title")}</Title>
      <Paragraph>{t("privacy.data_collected_text")}</Paragraph>
      <ul>
        <li>
          <strong>{t("privacy.account_data")}:</strong>{" "}
          {t("privacy.account_data_detail")}
        </li>
        <li>
          <strong>{t("privacy.member_data")}:</strong>{" "}
          {t("privacy.member_data_detail")}
        </li>
        <li>
          <strong>{t("privacy.payment_data")}:</strong>{" "}
          {t("privacy.payment_data_detail")}
        </li>
        <li>
          <strong>{t("privacy.usage_data")}:</strong>{" "}
          {t("privacy.usage_data_detail")}
        </li>
      </ul>

      <Divider />

      <Title level={4}>{t("privacy.purpose_title")}</Title>
      <Paragraph>{t("privacy.purpose_text")}</Paragraph>
      <ul>
        <li>
          <strong>{t("privacy.purpose_contract")}:</strong>{" "}
          {t("privacy.purpose_contract_detail")}
        </li>
        <li>
          <strong>{t("privacy.purpose_consent")}:</strong>{" "}
          {t("privacy.purpose_consent_detail")}
        </li>
        <li>
          <strong>{t("privacy.purpose_legitimate")}:</strong>{" "}
          {t("privacy.purpose_legitimate_detail")}
        </li>
      </ul>

      <Divider />

      <Title level={4}>{t("privacy.retention_title")}</Title>
      <Paragraph>{t("privacy.retention_text")}</Paragraph>

      <Divider />

      <Title level={4}>{t("privacy.rights_title")}</Title>
      <Paragraph>{t("privacy.rights_text")}</Paragraph>
      <ul>
        <li>{t("privacy.right_access")}</li>
        <li>{t("privacy.right_rectification")}</li>
        <li>{t("privacy.right_erasure")}</li>
        <li>{t("privacy.right_restriction")}</li>
        <li>{t("privacy.right_portability")}</li>
        <li>{t("privacy.right_objection")}</li>
      </ul>

      <Divider />

      <Title level={4}>{t("privacy.security_title")}</Title>
      <Paragraph>{t("privacy.security_text")}</Paragraph>

      <Divider />

      <Title level={4}>{t("privacy.third_parties_title")}</Title>
      <Paragraph>{t("privacy.third_parties_text")}</Paragraph>

      <Divider />

      <Title level={4}>{t("privacy.cookies_title")}</Title>
      <Paragraph>{t("privacy.cookies_text")}</Paragraph>

      <Divider />

      <Title level={4}>{t("privacy.contact_title")}</Title>
      <Paragraph>{t("privacy.contact_text")}</Paragraph>

      <Divider />

      <Title level={4}>{t("privacy.authority_title")}</Title>
      <Paragraph>{t("privacy.authority_text")}</Paragraph>
    </Typography>
  );
}
