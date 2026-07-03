/**
 * Step-up authentication bridge between the axios interceptor and the
 * React UI.
 *
 * The interceptor in ``services/api.ts`` runs outside React, so it
 * can't render a password modal directly. ``StepUpProvider`` (a React
 * component mounted high in the tree) registers a callback here at
 * mount time; the interceptor calls it when a destructive request
 * gets back a ``403 auth.step_up_required`` body.
 *
 * Concurrency
 * -----------
 * A single in-flight step-up flow handles every queued request. If
 * three destructive requests fire in quick succession and the first
 * lands on the gate, the other two await the same modal — we don't
 * want three password prompts stacked on top of each other.
 */

import axios from "axios";

import { isSuperAdminHostname } from "@shared/auth/superAdminHost";
import { getAccessToken, setAccessToken } from "./tokenStore";

export interface StepUpCredentials {
  password: string;
  /** Reserved for the post-TOTP rollout. The backend ignores it when
   *  ``STEP_UP_REQUIRES_TOTP`` is off, so it's optional. */
  totpCode?: string;
}

export interface StepUpPromptArgs {
  /** Seconds the new sudo-mode session will be valid for. From the
   *  ``StepUpRequired.details.ttl_seconds`` on the 403 body. The
   *  modal renders this as a "valid for N min" hint. */
  ttlSeconds: number;
  /** POSTs the credentials to the step-up endpoint and swaps the new
   *  access token in. Throws on a wrong password / throttle / network
   *  error — the modal catches, shows the error, and lets the user
   *  retry WITHOUT failing the original request. The modal must only
   *  resolve its prompt promise after this succeeded. */
  verify: (creds: StepUpCredentials) => Promise<void>;
}

/** Resolves once the user confirmed AND verification succeeded;
 *  rejects when the user cancels the modal. */
export type StepUpPrompt = (args: StepUpPromptArgs) => Promise<void>;

let promptImpl: StepUpPrompt | null = null;

/**
 * Called once by ``StepUpProvider`` on mount. The provider unregisters
 * (passes ``null``) on unmount so we don't hold a stale callback.
 */
export function registerStepUpPrompt(fn: StepUpPrompt | null): void {
  promptImpl = fn;
}

/**
 * Detect which realm we're in so the interceptor hits the right
 * step-up endpoint. Mirrors the (private) helper in ``api.ts``.
 */
function isSuperAdminHost(): boolean {
  if (typeof window === "undefined") return false;
  return isSuperAdminHostname(window.location.hostname);
}

function stepUpEndpoint(): string {
  return isSuperAdminHost()
    ? "/api/super-admin/auth/step-up/"
    : "/api/auth/step-up/";
}

let inFlight: Promise<string> | null = null;

/**
 * Open the step-up modal, verify the password against the step-up
 * endpoint (retrying inside the modal on a wrong password), swap the
 * new access token into the token store, and return it. Deduplicates:
 * if a flow is already in flight, additional callers wait on the same
 * promise (one modal, not three).
 */
export async function runStepUpFlow(args: {
  ttlSeconds: number;
}): Promise<string> {
  if (inFlight) return inFlight;
  if (!promptImpl) {
    // No provider mounted → we can't recover. Surface the original
    // 403 unchanged so the caller can decide what to do.
    return Promise.reject(
      new Error("Step-up prompt is not registered (StepUpProvider missing)."),
    );
  }

  inFlight = (async () => {
    try {
      // ``promptImpl`` is non-null here (checked above) but TS narrows
      // through closures conservatively — re-check + rethrow if it
      // raced. The provider only unregisters on unmount so this is
      // effectively never hit at runtime.
      const prompt = promptImpl;
      if (!prompt) {
        throw new Error("Step-up prompt was unregistered mid-flow.");
      }

      let newToken: string | null = null;
      // The modal calls ``verify`` on submit and stays open (showing
      // the error) when it throws — so a typo'd password costs one
      // retry, not the whole original action.
      await prompt({
        ttlSeconds: args.ttlSeconds,
        verify: async (creds: StepUpCredentials) => {
          const currentToken = getAccessToken();
          const { data } = await axios.post<{
            access: string;
            ttl_seconds: number;
          }>(
            stepUpEndpoint(),
            {
              password: creds.password,
              ...(creds.totpCode ? { totp_code: creds.totpCode } : {}),
            },
            {
              withCredentials: true,
              headers: currentToken
                ? { Authorization: `Bearer ${currentToken}` }
                : {},
            },
          );
          setAccessToken(data.access);
          newToken = data.access;
        },
      });

      if (newToken === null) {
        // The provider resolved without a successful verify — a
        // provider bug, but fail loudly rather than retrying the
        // original request with the stale token.
        throw new Error("Step-up prompt resolved without verification.");
      }
      return newToken;
    } finally {
      inFlight = null;
    }
  })();

  return inFlight;
}
