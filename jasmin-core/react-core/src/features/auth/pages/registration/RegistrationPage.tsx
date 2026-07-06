import { useMemo, useState } from "react";
import { Card, Steps, Typography } from "antd";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import StepCoopShares from "./steps/StepCoopShares";
import StepShareTypeVariation from "./steps/StepShareTypeVariation";
import StepConsents from "./steps/StepConsents";
import StepYourDetails from "./steps/StepYourDetails";
import StepConfirmEmail from "./steps/StepConfirmEmail";
import StepDone from "./steps/StepDone";
import type { RegistrationData } from "./types";

const { Title, Text } = Typography;

// Order (2026-07): coop shares → variation → consents → your details →
// confirm email → done. The account is created (+ set-password link emailed)
// only at the confirm-email step, once the address is verified.
const MEMBER_STEPS = [
  {
    titleKey: "auth.registration.steps.coop_shares",
    Component: StepCoopShares,
  },
  {
    titleKey: "auth.registration.steps.share_type_variation",
    Component: StepShareTypeVariation,
  },
  { titleKey: "auth.registration.steps.consents", Component: StepConsents },
  {
    titleKey: "auth.registration.steps.your_details",
    Component: StepYourDetails,
  },
  {
    titleKey: "auth.registration.steps.verify_email",
    Component: StepConfirmEmail,
  },
  { titleKey: "auth.registration.steps.done", Component: StepDone },
];

// Trial (Probe-Abo): same flow WITHOUT the coop-shares step — a trial member
// isn't a Genosse yet, so no shares are subscribed. The share step forces
// is_trial (from ``data.is_trial``) so ``valid_until`` is the trial end.
const TRIAL_STEPS = MEMBER_STEPS.filter(
  (s) => s.titleKey !== "auth.registration.steps.coop_shares",
);

export default function RegistrationPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const isTrial = searchParams.get("trial") === "1";

  const steps = useMemo(
    () => (isTrial ? TRIAL_STEPS : MEMBER_STEPS),
    [isTrial],
  );

  const [current, setCurrent] = useState(0);
  const [data, setData] = useState<RegistrationData>(
    isTrial ? { is_trial: true } : {},
  );

  const update = (partial: Partial<RegistrationData>) =>
    setData((prev) => ({ ...prev, ...partial }));

  const next = () => setCurrent((c) => Math.min(c + 1, steps.length - 1));
  const back = () => setCurrent((c) => Math.max(c - 1, 0));

  const { Component } = steps[current];

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        minHeight: "100vh",
        background: "var(--color-page-bg)",
        padding: "32px 16px",
      }}
    >
      <Card style={{ width: 1000, boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }}>
        <Title level={3} className="text-center">
          {t(
            isTrial
              ? "auth.registration.card_title_trial"
              : "auth.registration.card_title",
          )}
        </Title>

        <Steps
          current={current}
          items={steps.map((s) => ({ title: t(s.titleKey) }))}
          size="small"
          style={{ marginBottom: 24 }}
        />

        <Component data={data} update={update} next={next} back={back} />

        <div style={{ textAlign: "center", marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t("auth.registration.already_member")}{" "}
            <Link to="/login">{t("auth.registration.sign_in")}</Link>
          </Text>
        </div>
      </Card>
    </div>
  );
}
