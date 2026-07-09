import { Progress, Typography } from "antd";
import { clientPasswordScore } from "../utils/password";

const { Text } = Typography;

interface PasswordStrengthMeterProps {
  /** The raw password value; the 0–4 score is derived here. */
  password: string;
  /** Localized hint shown under the meter. */
  hint: string;
}

/**
 * Client-side password strength affordance for the reset / set-password forms:
 * a 4-step progress bar plus a muted hint. Real validation runs server-side
 * (zxcvbn ≥ 3); this only nudges users toward a passing password without a
 * round-trip. Owns {@link clientPasswordScore}.
 */
export function PasswordStrengthMeter({
  password,
  hint,
}: PasswordStrengthMeterProps) {
  const score = clientPasswordScore(password);
  const strokeColor =
    score >= 3
      ? "var(--color-success)"
      : score >= 2
        ? "var(--color-warning)"
        : "var(--color-error)";

  return (
    <>
      <Progress
        className="password-strength-meter"
        percent={(score / 4) * 100}
        showInfo={false}
        strokeColor={strokeColor}
      />
      <Text type="secondary" className="password-strength-hint">
        {hint}
      </Text>
    </>
  );
}
