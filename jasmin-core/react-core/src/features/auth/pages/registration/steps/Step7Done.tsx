import { Alert, Button, Descriptions, Flex, Result, Tag } from "antd";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { authRegisterCreate } from "@shared/api/generated/auth/auth";
import type { PublicRegisterRequest } from "@shared/api/generated/models";
import { getErrorMessage } from "@shared/utils/apiError";
import { FriendlyCaptcha } from "@shared/auth/FriendlyCaptcha";
import type { StepProps } from "../types";

// CSS to hide the honeypot from real users without using
// ``display: none`` (some bots skip ``display:none`` fields). Keeps
// the input in the DOM and tabbable-skip via ``tabIndex={-1}``.
const HONEYPOT_STYLE: React.CSSProperties = {
  position: "absolute",
  left: "-10000px",
  width: "1px",
  height: "1px",
  overflow: "hidden",
  opacity: 0,
};

export default function Step7Done({ data, back }: StepProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [captchaSolution, setCaptchaSolution] = useState("");
  const acceptedKinds = Object.keys(data.accepted_consent_documents ?? {});
  // Honeypot: hidden field that real users can't see + don't tab into.
  // Naive bots scrape the form, fill every input, and submit — their
  // value lands in ``honeypotRef.current.value``. Backend silently
  // accepts (fake-success) so they don't adapt; see
  // ``registration_service.register_public_applicant``.
  const honeypotRef = useRef<HTMLInputElement>(null);

  /**
   * Submit the registration as a single atomic call.
   *
   * Hits the public ``POST /api/auth/register/`` endpoint
   * (``authRegisterCreate``). The backend service
   * (``register_public_applicant``) creates everything inside one
   * ``@transaction.atomic`` block:
   *
   *   - JasminUser in ``pending_approval``
   *   - Member with ``admin_confirmed=False``
   *   - CoopShare if ``coop_shares_count > 0``
   *   - ConsentRecord per ``accepted_consent_documents`` entry
   *   - Subscription intent stashed on ``Member.note`` (office
   *     creates the real Subscription on confirm — wizard doesn't
   *     collect the FK fields a Subscription requires)
   *
   * Failure modes:
   *   - Anything raises -> whole transaction rolls back -> no
   *     orphaned rows. Surface the message; user can retry.
   */
  const handleSubmit = async () => {
    setSubmitting(true);
    setErrorMessage(null);

    // The wizard stores accepted documents as Partial<Record<string,
    // string>> (values can be undefined while the user backtracks).
    // The generated API type wants strict Record<string, string>, so
    // drop any undefined values before sending.
    const consents = Object.fromEntries(
      Object.entries(data.accepted_consent_documents ?? {}).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );

    const payload: PublicRegisterRequest = {
      email: data.email ?? "",
      password: data.password ?? "",
      first_name: data.first_name,
      last_name: data.last_name,
      coop_shares_count: data.coop_shares_count,
      share_type_variation_id:
        data.share_type_variation_id != null
          ? String(data.share_type_variation_id)
          : undefined,
      quantity: data.quantity,
      accepted_consent_documents:
        Object.keys(consents).length > 0 ? consents : undefined,
      // Honeypot value — always empty for real users. Bots may have
      // filled it; that lands the request in the backend's
      // silent-discard path.
      website: honeypotRef.current?.value ?? "",
      // Friendly Captcha solution. Ignored by the backend when
      // FRIENDLY_CAPTCHA_ENABLED=False. The widget renders nothing
      // when no sitekey is configured.
      frc_captcha_solution: captchaSolution,
    };

    try {
      await authRegisterCreate(payload);
    } catch (err) {
      setErrorMessage(getErrorMessage(err));
      setSubmitting(false);
      return;
    }

    navigate("/login");
  };

  return (
    <>
      {/* Honeypot input — hidden from real users; bots see + fill it. */}
      <input
        ref={honeypotRef}
        type="text"
        name="website"
        autoComplete="off"
        tabIndex={-1}
        aria-hidden="true"
        style={HONEYPOT_STYLE}
        defaultValue=""
      />
      <Result
        status="success"
        title={t("auth.registration.step5.title")}
        subTitle={t("auth.registration.step5.subtitle")}
      />

      <Descriptions
        column={1}
        bordered
        size="small"
        style={{ marginBottom: 24 }}
      >
        <Descriptions.Item label={t("auth.registration.step5.name")}>
          {data.first_name} {data.last_name}
        </Descriptions.Item>
        <Descriptions.Item label={t("auth.registration.step5.email")}>
          {data.email}
        </Descriptions.Item>
        <Descriptions.Item label={t("auth.registration.step5.email_verified")}>
          {data.email_verified
            ? t("auth.registration.step5.yes")
            : t("auth.registration.step5.no")}
        </Descriptions.Item>
        <Descriptions.Item label={t("auth.registration.step5.coop_shares")}>
          {data.coop_shares_count}
        </Descriptions.Item>
        <Descriptions.Item label={t("auth.registration.step5.share_type_variation")}>
          {data.share_type_variation_id} × {data.quantity}
        </Descriptions.Item>
        <Descriptions.Item label={t("auth.registration.step5.consents")}>
          {acceptedKinds.length === 0 ? (
            t("auth.registration.step5.no")
          ) : (
            <>
              {acceptedKinds.map((k) => (
                <Tag key={k} color="green" style={{ marginBottom: 4 }}>
                  {t(`consent.kind.${k}`, k)}
                </Tag>
              ))}
            </>
          )}
        </Descriptions.Item>
      </Descriptions>

      {errorMessage && (
        <Alert
          type="error"
          showIcon
          message={errorMessage}
          style={{ marginBottom: 16 }}
        />
      )}

      <FriendlyCaptcha onSolution={setCaptchaSolution} />

      <Flex justify="space-between" gap="small">
        <Button onClick={back} disabled={submitting}>
          {t("auth.registration.actions.back")}
        </Button>
        <Button type="primary" onClick={handleSubmit} loading={submitting}>
          {t("auth.registration.actions.submit")}
        </Button>
      </Flex>
    </>
  );
}
