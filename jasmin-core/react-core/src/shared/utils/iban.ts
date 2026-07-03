import {
  friendlyFormatIBAN,
  ValidationErrorsIBAN,
  validateIBAN,
} from "ibantools";

/**
 * IBAN validation helpers wired around the ``ibantools`` library.
 * The library runs the ISO 13616 mod-97 check + country-specific
 * length table — same algorithm the backend's ``IBANValidator``
 * applies in Django, so the two layers stay in agreement.
 *
 * What this util does NOT do: verify the IBAN points at a real, open
 * bank account. That would require a SEPA reachability lookup; it's
 * out of scope here.
 */

export type IbanCheck =
  | { valid: true; formatted: string }
  | {
      valid: false;
      /** ibantools' fine-grained error codes for the office UI to
       *  surface a specific message. */
      reasons: ValidationErrorsIBAN[];
    };

/**
 * Lenient pre-check: whitespace + casing are normalised before the
 * mod-97 runs. Matches the backend behaviour
 * (``IBANValidator`` strips whitespace before calling
 * ``stdnum.iban.validate``).
 *
 * Returns ``{valid: true, formatted}`` for the displayable spaced
 * version when the IBAN is well-formed. Otherwise the discriminated
 * union's ``valid: false`` carries the ibantools error codes so the
 * caller can render a specific reason ("checksum failed" vs "wrong
 * length for the country code" vs ...).
 */
export function checkIban(value: string | null | undefined): IbanCheck {
  if (!value) {
    // Treat empty as valid — matches the backend (``blank=True``
    // fields don't require a value). Callers that need "must be
    // present" do the check separately.
    return { valid: true, formatted: "" };
  }
  const normalized = value.replace(/\s/g, "").toUpperCase();
  const result = validateIBAN(normalized);
  if (result.valid) {
    return { valid: true, formatted: friendlyFormatIBAN(normalized) ?? "" };
  }
  return { valid: false, reasons: result.errorCodes ?? [] };
}

/**
 * Translate ibantools' error codes into a single human-readable
 * summary. Matches the backend ``IBANValidator``'s single-code
 * contract — both layers reject malformed IBANs with the same
 * message instead of trying to distinguish format / length /
 * checksum sub-cases (the distinction wasn't reliable in
 * ``python-stdnum`` 2.x).
 *
 * ``reasons`` is accepted for API symmetry with the backend but
 * unused in the message resolution. Kept on the signature so
 * future fine-grained messages can be wired in without touching
 * call sites.
 */
export function formatIbanError(
  _reasons: ValidationErrorsIBAN[],
  t: (key: string) => string,
): string {
  return t("validation.iban_invalid");
}

/**
 * BIC (ISO 9362) format check. The pattern is the EXACT one the SEPA
 * pain.008.001.02 XSD enforces — 6 letters (bank code) + 1 check char +
 * 1 location char + optional 3-char branch (so 8 or 11 chars total,
 * letters first). Mirroring the XSD client-side means the office gets
 * immediate feedback instead of a 400 at SEPA-export time (which is the
 * only place this is otherwise checked).
 *
 * Empty passes (the field is ``blank=True`` on the model; "must be
 * present" is enforced at export, like the IBAN). Whitespace + casing
 * are normalised first.
 */
const BIC_PATTERN = /^[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?$/;

export function checkBic(value: string | null | undefined): { valid: boolean } {
  if (!value || value.trim() === "") return { valid: true };
  return { valid: BIC_PATTERN.test(value.replace(/\s/g, "").toUpperCase()) };
}
