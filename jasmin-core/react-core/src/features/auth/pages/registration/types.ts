/**
 * Shared state collected across the membership-registration wizard.
 *
 * Order (2026-07): coop shares → variation → consents → your details →
 * confirm email → done. The account is created (and the set-password link
 * emailed) only at the confirm-email step, once the address is verified —
 * the wizard never collects a password.
 *
 * Keep this purely serialisable so we can later persist it (sessionStorage)
 * for refresh-resilience if needed.
 */
export interface RegistrationData {
  // Step 1 — cooperative shares + the Zeichnungsvertrag (coop_contract)
  // consent captured alongside them.
  coop_shares_count?: number;

  // Step 2 — subscription intent (from the public NewSubscriptionModal). We
  // record the CHOICE only; the office materialises the real (capacity-checked)
  // Subscription on confirm.
  share_type_variation_id?: string;
  quantity?: number;
  default_delivery_station_day?: string;
  price_per_delivery?: string;
  payment_cycle?: string;
  valid_from?: string;
  valid_until?: string;

  // Trial (Probe-Abo) registration: set from the ``?trial`` entry point.
  // Trial members skip the coop-shares step and their subscription intent is a
  // trial bounded by valid_from/valid_until.
  is_trial?: boolean;

  // Steps 1 + 3 — accepted consents, keyed by ConsentKind → the
  // ConsentDocument id the user agreed to (proof of which version was shown).
  // On the final submit the backend records one ConsentRecord per entry.
  accepted_consent_documents?: Partial<Record<string, string>>;

  // Step 4 — identity.
  first_name?: string;
  last_name?: string;
  email?: string;
  address?: string;
  zip_code?: string;
  city?: string;
  country?: string;

  // Step 5 — email ownership proven via the code check.
  email_verified?: boolean;
}

export interface StepProps {
  data: RegistrationData;
  update: (partial: Partial<RegistrationData>) => void;
  next: () => void;
  back: () => void;
}
