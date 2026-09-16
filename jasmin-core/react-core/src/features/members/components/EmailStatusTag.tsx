import { Tag, Tooltip } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { getEmailStatusColor } from "@shared/utils/emailStatusColors";

interface EmailStatusTagProps {
  /** An ``EmailLog`` status, e.g. ``sent`` or ``suppressed``. */
  status: string;
}

/**
 * An email log status as a colored tag with a short label. A suppressed email
 * also says why it was not sent: in a light tooltip on hover, and as the tag's
 * accessible description.
 */
export default function EmailStatusTag({ status }: EmailStatusTagProps) {
  const { t } = useTranslation();
  const hintId = useId();
  const label = t(`email_matrix.status.${status}`);

  if (status !== "suppressed") {
    return (
      <Tag color={getEmailStatusColor(status)} className="email-status-tag">
        {label}
      </Tag>
    );
  }

  const hint = t("email_matrix.status_hint.suppressed");
  return (
    <Tooltip
      title={hint}
      trigger="hover"
      classNames={{ root: "custom-tooltip" }}
    >
      {/* The tooltip sets its own aria-describedby on its direct child, so the
          tag inside keeps the hint as its description. */}
      <span>
        <Tag
          color={getEmailStatusColor(status)}
          className="email-status-tag"
          aria-describedby={hintId}
        >
          {label}
        </Tag>
        <span id={hintId} className="sr-only">
          {hint}
        </span>
      </span>
    </Tooltip>
  );
}
