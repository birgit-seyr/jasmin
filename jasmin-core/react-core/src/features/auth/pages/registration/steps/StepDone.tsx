import { Button, Result, Typography } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { StepProps } from "../types";

const { Paragraph } = Typography;

/**
 * Step 6 — done. The account exists (pending) and a set-password link was
 * emailed; the office will review the membership. Explains both next steps.
 */
export default function StepDone({ data }: StepProps) {
  const { t } = useTranslation();

  return (
    <Result
      status="success"
      title={t("auth.registration.done.title")}
      subTitle={t("auth.registration.done.subtitle", { email: data.email })}
      extra={
        <>
          <Paragraph type="secondary" style={{ textAlign: "left" }}>
            {t("auth.registration.done.set_password")}
          </Paragraph>
          <Paragraph type="secondary" style={{ textAlign: "left" }}>
            {t("auth.registration.done.office_review")}
          </Paragraph>
          <Link to="/login">
            <Button type="primary">
              {t("auth.registration.done.to_login")}
            </Button>
          </Link>
        </>
      }
    />
  );
}
