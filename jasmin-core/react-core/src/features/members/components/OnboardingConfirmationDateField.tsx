import { DatePicker, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useId } from "react";
import { useTranslation } from "react-i18next";
import { useDateFormat } from "@hooks/index";

const { Paragraph } = Typography;

interface OnboardingConfirmationDateFieldProps {
  value: Dayjs;
  onChange: (value: Dayjs | null) => void;
  /** A departed member's exit date; later days can't be picked. */
  exitDate?: string | null;
}

/**
 * Date picker for the confirmation date in the member and coop share confirm
 * modals, rendered only while the tenant's onboarding mode is on. Future days
 * and days after a departed member's exit date are disabled; the server
 * refuses both as well.
 */
export function OnboardingConfirmationDateField({
  value,
  onChange,
  exitDate = null,
}: OnboardingConfirmationDateFieldProps) {
  const { t } = useTranslation();
  const { dateFormat, formatDate } = useDateFormat();
  const inputId = useId();
  const hintId = useId();

  const disabledDate = useCallback(
    (current: Dayjs) =>
      current.isAfter(dayjs(), "day") ||
      (!!exitDate && current.isAfter(dayjs(exitDate), "day")),
    [exitDate],
  );

  return (
    <div className="onboarding-confirmation-date">
      <label htmlFor={inputId} className="onboarding-confirmation-date__label">
        {t("onboarding.confirmation_date.label")}
      </label>
      <DatePicker
        id={inputId}
        value={value}
        onChange={onChange}
        format={dateFormat}
        allowClear={false}
        disabledDate={disabledDate}
        aria-describedby={hintId}
        className="onboarding-confirmation-date__picker"
      />
      <Paragraph
        id={hintId}
        type="secondary"
        className="onboarding-confirmation-date__hint"
      >
        {exitDate
          ? t("onboarding.confirmation_date.hint_departed", {
              date: formatDate(exitDate),
            })
          : t("onboarding.confirmation_date.hint")}
      </Paragraph>
    </div>
  );
}
