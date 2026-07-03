import { useState } from "react";
import { Card, Steps, Typography } from "antd";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Step1NameEmail from "./steps/Step1NameEmail";
import Step2VerifyEmail from "./steps/Step2VerifyEmail";
import Step3CoopShares from "./steps/Step3CoopShares";
import Step4ShareTypeVariation from "./steps/Step4ShareTypeVariation";
import Step5Consents from "./steps/Step5Consents";
import Step6Password from "./steps/Step6Password";
import Step7Done from "./steps/Step7Done";
import type { RegistrationData } from "./types";

const { Title, Text } = Typography;

const STEPS = [
  {
    titleKey: "auth.registration.steps.your_details",
    Component: Step1NameEmail,
  },
  {
    titleKey: "auth.registration.steps.verify_email",
    Component: Step2VerifyEmail,
  },
  {
    titleKey: "auth.registration.steps.coop_shares",
    Component: Step3CoopShares,
  },
  {
    titleKey: "auth.registration.steps.share_variation",
    Component: Step4ShareTypeVariation,
  },
  {
    titleKey: "auth.registration.steps.consents",
    Component: Step5Consents,
  },
  {
    titleKey: "auth.registration.steps.password",
    Component: Step6Password,
  },
  { titleKey: "auth.registration.steps.done", Component: Step7Done },
];

export default function RegistrationPage() {
  const { t } = useTranslation();
  const [current, setCurrent] = useState(0);
  const [data, setData] = useState<RegistrationData>({});

  const update = (partial: Partial<RegistrationData>) =>
    setData((prev) => ({ ...prev, ...partial }));

  const next = () => setCurrent((c) => Math.min(c + 1, STEPS.length - 1));
  const back = () => setCurrent((c) => Math.max(c - 1, 0));

  const { Component } = STEPS[current];

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
      <Card style={{ width: 640, boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }}>
        <Title level={3} className="text-center">
          {t("auth.registration.card_title")}
        </Title>

        <Steps
          current={current}
          items={STEPS.map((s) => ({ title: t(s.titleKey) }))}
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
