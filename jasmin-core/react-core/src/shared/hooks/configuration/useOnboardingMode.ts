import { useTenant } from "./useTenant";

/**
 * Whether the tenant's onboarding mode is on. While it is, the server sends no
 * member emails (admission, rejection, cancellation, trial conversion, member
 * portal invitations, waiting-list offers) and refuses the office actions whose
 * only purpose is such an email. Only a stored ``true`` counts as on.
 */
export function useOnboardingMode(): boolean {
  const { getSetting } = useTenant();
  return getSetting("onboarding_mode", false) === true;
}
