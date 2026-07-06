import { Alert, Button, Flex, Form, Input, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useAuthRegisterCreate,
  useAuthRegisterSendCodeCreate,
  useAuthRegisterVerifyCodeCreate,
} from "@shared/api/generated/auth/auth";
import type { UserLanguageEnum } from "@shared/api/generated/models";
import { FriendlyCaptcha } from "@shared/auth/FriendlyCaptcha";
import { useTenant } from "@hooks/index";
import { getErrorMessage } from "@shared/utils/apiError";
import type { StepProps } from "../types";

const { Paragraph, Text } = Typography;

const LANGS = ["de", "en", "fr", "it"];

/**
 * Step 5 — confirm the email address. On entering we email a code; the
 * applicant enters it, and on success we submit the full registration (which
 * creates the pending account and emails the set-password link). No password
 * is collected here.
 */
export default function StepConfirmEmail({ data, update, next, back }: StepProps) {
  const { t, i18n } = useTranslation();
  const { tenant } = useTenant();
  const [form] = Form.useForm<{ code: string }>();
  const [error, setError] = useState("");
  const [captchaSolution, setCaptchaSolution] = useState("");

  const sendCode = useAuthRegisterSendCodeCreate();
  const verifyCode = useAuthRegisterVerifyCodeCreate();
  const register = useAuthRegisterCreate();

  const email = data.email ?? "";
  const sentForEmail = useRef<string | null>(null);
  // Once verifyCode succeeds the code is consumed server-side; a retry after a
  // transient register failure must NOT re-verify (the code is burned) — it
  // just replays register against the still-valid verified marker.
  const verifiedRef = useRef(false);
  // Guard against a double Enter racing two verify/register runs.
  const inFlightRef = useRef(false);

  // Friendly Captcha gates the FIRST anonymous send. Empty sitekey (FC off,
  // the default) → the widget renders nothing and we send immediately.
  const captchaEnabled = Boolean(tenant?.friendly_captcha_sitekey);

  const doSend = () => {
    setError("");
    sendCode.mutate({
      data: {
        email,
        first_name: data.first_name ?? "",
        frc_captcha_solution: captchaSolution,
      },
    });
  };

  useEffect(() => {
    if (!email || sentForEmail.current === email) return;
    // When FC is enabled, wait for a solution before the auto-send.
    if (captchaEnabled && !captchaSolution) return;
    sentForEmail.current = email;
    doSend();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email, captchaEnabled, captchaSolution]);

  const buildPayload = () => {
    const consents: Record<string, string> = {};
    for (const [k, v] of Object.entries(data.accepted_consent_documents ?? {})) {
      if (v) consents[k] = v;
    }
    const langBase = (i18n.language || "en").split("-")[0];
    return {
      email,
      first_name: data.first_name ?? "",
      last_name: data.last_name ?? "",
      address: data.address,
      zip_code: data.zip_code,
      city: data.city,
      country: data.country,
      coop_shares_count: data.coop_shares_count,
      share_type_variation_id: data.share_type_variation_id,
      quantity: data.quantity,
      default_delivery_station_day: data.default_delivery_station_day,
      price_per_delivery: data.price_per_delivery,
      payment_cycle: data.payment_cycle,
      is_trial: data.is_trial ?? false,
      valid_from: data.valid_from,
      valid_until: data.valid_until,
      accepted_consent_documents: Object.keys(consents).length
        ? consents
        : undefined,
      user_language: (LANGS.includes(langBase)
        ? langBase
        : "en") as UserLanguageEnum,
    };
  };

  const handleFinish = async (values: { code: string }) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setError("");
    try {
      if (!verifiedRef.current) {
        await verifyCode.mutateAsync({
          data: { email, code: values.code.trim() },
        });
        verifiedRef.current = true;
      }
      await register.mutateAsync({ data: buildPayload() });
      update({ email_verified: true });
      next();
    } catch (err) {
      setError(getErrorMessage(err, t("auth.registration.confirm.error")));
    } finally {
      inFlightRef.current = false;
    }
  };

  const submitting = verifyCode.isPending || register.isPending;
  const canSend = !captchaEnabled || Boolean(captchaSolution);

  return (
    <>
      <Paragraph>{t("auth.registration.confirm.intro", { email })}</Paragraph>

      <FriendlyCaptcha onSolution={setCaptchaSolution} />

      {sendCode.isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={getErrorMessage(
            sendCode.error,
            t("auth.registration.confirm.send_error"),
          )}
        />
      )}

      <Form form={form} layout="vertical" onFinish={handleFinish} size="large">
        <Form.Item
          name="code"
          label={t("auth.registration.confirm.code_label")}
          rules={[
            {
              required: true,
              message: t("auth.registration.confirm.code_required"),
            },
          ]}
        >
          <Input
            placeholder="123456"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
          />
        </Form.Item>

        {error && (
          <Alert
            type="error"
            showIcon
            message={error}
            style={{ marginBottom: 12 }}
          />
        )}

        <Flex justify="space-between" align="center">
          <Button onClick={back} disabled={submitting}>
            {t("auth.registration.actions.back")}
          </Button>
          <Flex gap="small" align="center">
            <Button
              type="link"
              onClick={doSend}
              loading={sendCode.isPending}
              disabled={submitting || !canSend}
            >
              {t("auth.registration.confirm.resend")}
            </Button>
            <Button type="primary" htmlType="submit" loading={submitting}>
              {t("auth.registration.confirm.submit")}
            </Button>
          </Flex>
        </Flex>
      </Form>

      <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 12 }}>
        {t("auth.registration.confirm.hint")}
      </Text>
    </>
  );
}
