/**
 * Shared state collected across all steps of the membership registration
 * wizard. Each step receives the current `data` and an `update` callback
 * that merges a partial into it. Keep this purely serialisable so we can
 * later persist it (sessionStorage) for refresh-resilience if needed.
 */
export interface RegistrationData {
  // Step 1: identity
  first_name?: string;
  last_name?: string;
  email?: string;

  // Step 2: email verification
  email_verification_code?: string;
  email_verified?: boolean;

  // Step 3: coop shares
  coop_shares_count?: number;

  // Step 4: share-type variation order
  share_type_variation_id?: string | number;
  quantity?: number;

  // Step 5: consents.
  // ``accepted_consent_documents`` is keyed by ConsentKind and holds
  // the ConsentDocument *id* the user agreed to (proof of which
  // version was shown). On submit (Step 7) the backend creates one
  // ``ConsentRecord`` per entry atomically alongside the Member.
  accepted_consent_documents?: Partial<Record<string, string>>;

  // Step 6: account credentials
  // Plaintext password collected just before the final submit and
  // sent to ``POST /api/auth/register/`` over HTTPS — never persisted
  // client-side beyond this in-memory wizard state.
  password?: string;
}

export interface StepProps {
  data: RegistrationData;
  update: (partial: Partial<RegistrationData>) => void;
  next: () => void;
  back: () => void;
}
