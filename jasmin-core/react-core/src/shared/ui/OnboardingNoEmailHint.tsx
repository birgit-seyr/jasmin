import { MailOutlined } from "@ant-design/icons";
import { Typography } from "antd";
import { useTranslation } from "react-i18next";
import { useOnboardingMode } from "@hooks/index";

const { Paragraph } = Typography;

/**
 * Short note for a form whose action would email a member. Shown only while the
 * tenant's onboarding mode is on, when that email is not sent, so a form can
 * mount it unconditionally.
 */
export default function OnboardingNoEmailHint() {
  const { t } = useTranslation();
  const onboardingMode = useOnboardingMode();

  if (!onboardingMode) return null;

  return (
    <Paragraph type="secondary" className="onboarding-no-email-hint">
      <MailOutlined aria-hidden="true" /> {t("onboarding.mode.no_email_hint")}
    </Paragraph>
  );
}
