import { Alert, Typography } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { useTenant, useTenantSettingToggle } from "@hooks/index";
import LabeledSwitch from "@shared/ui/LabeledSwitch";

const { Paragraph } = Typography;

/**
 * Warning banner for the top of the Members and Abos pages. Renders nothing
 * while the tenant's onboarding mode is off, so a page can mount it
 * unconditionally.
 */
export function OnboardingModeBanner() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const titleId = useId();

  if (getSetting("onboarding_mode", false) !== true) return null;

  return (
    <section aria-labelledby={titleId} className="onboarding-mode-banner">
      <Alert
        type="warning"
        showIcon
        message={<span id={titleId}>{t("onboarding.mode.banner_title")}</span>}
        description={
          <>
            <Paragraph className="onboarding-mode-banner__intro">
              {t("onboarding.mode.banner_intro")}
            </Paragraph>
            <ul className="onboarding-mode-banner__effects">
              <li>{t("onboarding.mode.effects.no_emails")}</li>
              <li>{t("onboarding.mode.effects.confirmation_dates")}</li>
              <li>{t("onboarding.mode.effects.member_fields")}</li>
              <li>{t("onboarding.mode.effects.past_start")}</li>
              <li>{t("onboarding.mode.effects.backfill")}</li>
              <li>{t("onboarding.mode.effects.departed_members")}</li>
              <li>{t("onboarding.mode.effects.confirm_members_first")}</li>
            </ul>
            <Paragraph className="onboarding-mode-banner__outro">
              {t("onboarding.mode.banner_outro")}
            </Paragraph>
          </>
        }
      />
    </section>
  );
}

/**
 * Office switch that turns the tenant's onboarding mode on or off. Changing it
 * is step-up sensitive on the server; the shared API interceptor prompts for
 * the password and retries.
 */
export function OnboardingModeSwitch() {
  const { t } = useTranslation();
  const { value, onChange, saving } = useTenantSettingToggle(
    "onboarding_mode",
    false,
  );
  const hintId = useId();

  return (
    <div className="onboarding-mode-switch">
      <LabeledSwitch
        value={value}
        onChange={(checked) => void onChange(checked)}
        loading={saving}
        label={t("onboarding.mode.switch_label")}
        describedBy={hintId}
      />
      <Paragraph
        id={hintId}
        type="secondary"
        className="onboarding-mode-switch__hint"
      >
        {t("onboarding.mode.switch_hint")}
      </Paragraph>
    </div>
  );
}
