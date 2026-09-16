import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useMemo, useState } from "react";
import type { AdminConfirmationRequest } from "@shared/api/generated/models";
import { useDateFormat, useTenant } from "@hooks/index";

interface UseOnboardingConfirmationDateOptions {
  /** The record being confirmed. Another record starts again from its own
   *  default date. */
  recordId?: string | null;
  /** The member's entry date; the default confirmation date when set and not
   *  in the future. */
  entryDate?: string | null;
  /** The member's exit date (``cancelled_effective_at``) when they have left.
   *  The default never lies after it. */
  exitDate?: string | null;
}

/**
 * Confirmation date for the member and coop share confirm modals. While the
 * tenant's onboarding mode is on, the office dates a confirmation that happened
 * before Jasmin: the date defaults to the member's entry date (else today; never
 * after today, which the server refuses, nor after a departed member's exit
 * date) and is sent as ``confirmed_at``.
 * While the mode is off the confirm body stays empty, because the server
 * refuses a date then.
 */
export function useOnboardingConfirmationDate({
  recordId = null,
  entryDate = null,
  exitDate = null,
}: UseOnboardingConfirmationDateOptions) {
  const { getSetting } = useTenant();
  const onboardingMode = getSetting("onboarding_mode", false) === true;
  const { formatDateForAPI } = useDateFormat();

  const defaultDate = useMemo(() => {
    const today = dayjs().startOf("day");
    const preferred =
      entryDate && !dayjs(entryDate).isAfter(today, "day")
        ? dayjs(entryDate)
        : today;
    return exitDate && preferred.isAfter(dayjs(exitDate), "day")
      ? dayjs(exitDate)
      : preferred;
  }, [entryDate, exitDate]);

  // The picked date belongs to one record, so opening the modal for another
  // record shows that record's default instead of a stale pick.
  const [picked, setPicked] = useState<{
    recordId: string | null;
    value: Dayjs;
  } | null>(null);
  const confirmedOn =
    picked && picked.recordId === recordId ? picked.value : defaultDate;

  const setConfirmedOn = useCallback(
    (value: Dayjs | null) => {
      if (value) setPicked({ recordId, value });
    },
    [recordId],
  );

  const confirmationBody = useCallback(
    (): AdminConfirmationRequest =>
      onboardingMode ? { confirmed_at: formatDateForAPI(confirmedOn) } : {},
    [onboardingMode, formatDateForAPI, confirmedOn],
  );

  return { onboardingMode, confirmedOn, setConfirmedOn, confirmationBody };
}
