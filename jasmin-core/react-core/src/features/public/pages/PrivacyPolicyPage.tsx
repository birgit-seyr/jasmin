import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Card } from "antd";
import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useTenant } from "@hooks/index";
import DefaultPrivacyPolicyTemplate from "./DefaultPrivacyPolicyTemplate";

export default function PrivacyPolicyPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { tenant } = useTenant();

  // Per-tenant override wins. When ``Tenant.privacy_policy_html`` is
  // set, the tenant has authored its own policy via the
  // ConfigurationGDPR editor and we render that verbatim. Empty /
  // missing → fall back to the shared ``DefaultPrivacyPolicyTemplate``
  // (which still pulls the tenant's address + contact from ``tenant.*``).
  // The override is HTML because the editor on ConfigurationGDPR is a
  // rich-text editor; the static template is a structured React tree.
  const tenantPolicyHtml = (
    tenant as { privacy_policy_html?: string } | null | undefined
  )?.privacy_policy_html?.trim();

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--color-page-bg)",
        padding: "40px 24px",
      }}
    >
      <Card
        style={{
          maxWidth: 800,
          margin: "0 auto",
        }}
      >
        <Button
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(-1)}
          style={{ padding: 0, marginBottom: 16 }}
        >
          {t("common.back")}
        </Button>

        {tenantPolicyHtml ? (
          // The source is the tenant's OWN privacy policy, authored by
          // the tenant's admin via the rich-text editor on
          // ConfigurationGDPR. Sanitised anyway: this page is public and
          // the stored HTML could be set through other channels than the
          // editor (API, DB), so don't rely on the editor being
          // script-free.
          <div
            className="tenant-privacy-policy"
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(tenantPolicyHtml),
            }}
          />
        ) : (
          <DefaultPrivacyPolicyTemplate tenant={tenant} />
        )}
      </Card>
    </div>
  );
}
