/**
 * Friendly Captcha widget wrapper.
 *
 * Renders the FC challenge on every anonymous auth form (login,
 * register, forgot-password, reset-password). Mounts the official
 * ``@friendlycaptcha/sdk`` web component and lifts the solution
 * string up to the parent form via ``onSolution``.
 *
 * Feature-flag-off behaviour
 * --------------------------
 * The sitekey is sourced from ``TenantContext.tenant.friendly_captcha_sitekey``,
 * which the backend ships as an empty string when
 * ``FRIENDLY_CAPTCHA_ENABLED=False``. Empty sitekey -> component
 * returns ``null`` and the form proceeds as before. So forms can
 * mount this unconditionally; nothing renders until the operator
 * flips the flag + ships keys.
 *
 * Behaviour when enabled
 * ----------------------
 *   1. On mount, the FC widget starts solving its proof-of-work in
 *      the background. The user sees a small "verifying…" badge.
 *   2. When the solution is ready, ``onSolution(token)`` fires.
 *   3. The parent form should keep its submit button disabled until
 *      it has received a non-empty solution (or the form should
 *      submit the empty string and let the backend reject — same
 *      effect, slightly worse UX).
 *
 * Library: ``@friendlycaptcha/sdk`` registers ``<frc-captcha>`` as a
 * web component on import side-effect. We import it once at the
 * module level rather than per-mount.
 */

import { useEffect, useRef } from "react";

import { useTenant } from "@hooks/index";

// Side-effect import: registers the <frc-captcha> custom element on
// the global registry. Safe to import multiple times; the SDK guards
// against double-registration internally.
import "@friendlycaptcha/sdk";

// The <frc-captcha> element is a Web Component, not a React element —
// declare it on JSX.IntrinsicElements so TS doesn't complain.
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "frc-captcha": React.DetailedHTMLProps<
        React.HTMLAttributes<HTMLElement> & { sitekey?: string },
        HTMLElement
      >;
    }
  }
}

interface FriendlyCaptchaProps {
  /**
   * Called with the solution string when the FC widget completes its
   * proof-of-work. Also called with the empty string on reset / error.
   * Parent form should treat any non-empty value as "ready to submit".
   */
  onSolution: (solution: string) => void;
}

export function FriendlyCaptcha({ onSolution }: FriendlyCaptchaProps) {
  const { tenant } = useTenant();
  const sitekey =
    (tenant?.friendly_captcha_sitekey as string | undefined) ?? "";

  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!sitekey) return;
    const el = containerRef.current?.querySelector("frc-captcha");
    if (!el) return;

    // FC emits ``frc:widget.complete`` (solution ready) and
    // ``frc:widget.error`` (challenge failed / expired). Both names
    // are stable since SDK v0.1.x.
    const handleComplete = (event: Event) => {
      const detail = (event as CustomEvent<{ response?: string }>).detail;
      onSolution(detail?.response ?? "");
    };
    const handleError = () => onSolution("");

    el.addEventListener("frc:widget.complete", handleComplete);
    el.addEventListener("frc:widget.error", handleError);
    return () => {
      el.removeEventListener("frc:widget.complete", handleComplete);
      el.removeEventListener("frc:widget.error", handleError);
    };
  }, [sitekey, onSolution]);

  if (!sitekey) return null;

  return (
    <div ref={containerRef} className="frc-captcha-mount">
      {/* The web component starts solving on mount. No props beyond
          ``sitekey`` are needed for the default invisible flow. */}
      <frc-captcha sitekey={sitekey} />
    </div>
  );
}

export default FriendlyCaptcha;
