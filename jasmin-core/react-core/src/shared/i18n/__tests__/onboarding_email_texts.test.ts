/**
 * The email log renders ``email_matrix.status.<status>`` with a dynamic key the
 * missing-translation scan can't see, so every status the API can return needs
 * a de and en label here. The onboarding-mode email texts (banner effect,
 * hints, tooltips, rejection copy) must exist in both languages too.
 */

import { describe, expect, it } from "vitest";

import { EmailLogStatusEnum } from "@shared/api/generated/models/emailLogStatusEnum";
import de from "../locales/de";
import en from "../locales/en";

const BUNDLES = { de, en } as const;

function lookup(bundle: unknown, dottedKey: string): unknown {
  return dottedKey
    .split(".")
    .reduce<unknown>(
      (node, part) =>
        node && typeof node === "object"
          ? (node as Record<string, unknown>)[part]
          : undefined,
      bundle,
    );
}

const ONBOARDING_EMAIL_KEYS = [
  "onboarding.mode.effects.no_emails",
  "onboarding.mode.no_email_hint",
  "onboarding.mode.invitation_disabled",
  "onboarding.mode.offer_spot_disabled",
  "onboarding.mode.reject_warning_title",
  "onboarding.mode.reject_warning_body",
  "onboarding.mode.reject_reason_label",
  "email_matrix.commissioning.waiting_list_offer",
  "email_matrix.commissioning.member_self_cancelled_office",
  "email_matrix.commissioning.subscription_renewal_failures_office",
  "errors.onboarding_mode.email_action_blocked",
  "email_matrix.status_hint.suppressed",
  "members.application_pending_subtitle_no_email",
];

describe.each(Object.entries(BUNDLES))("%s locale", (_language, bundle) => {
  it.each(Object.values(EmailLogStatusEnum))(
    "labels the email status %s",
    (status) => {
      const label = lookup(bundle, `email_matrix.status.${status}`);
      expect(typeof label).toBe("string");
      expect(label).not.toBe("");
    },
  );

  it.each(ONBOARDING_EMAIL_KEYS)("has the text %s", (key) => {
    const text = lookup(bundle, key);
    expect(typeof text).toBe("string");
    expect(text).not.toBe("");
  });
});
