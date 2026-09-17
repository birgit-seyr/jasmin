"""Payments-app domain errors.

All subclasses of :class:`core.errors.JasminError`, so the global
exception handler renders them as the canonical
``{code, message, field?, details?}`` body with the right HTTP status —
services raise, the viewsets don't re-wrap them as bare DRF
``ValidationError`` (which would erase the stable code).
"""

from __future__ import annotations

from core.errors import BadRequestError, ConflictError

# ``InvalidQueryParam`` (code ``query.invalid_param``) is single-sourced in
# ``core.errors`` — import it from there (payments/viewsets does).


class BillingRunInvalidPeriod(BadRequestError):
    """``period_end`` is before ``period_start``."""

    code = "billing_run.invalid_period"


class BillingRunInvalidCollectionDate(BadRequestError):
    """The SEPA ``collection_date`` is in the past. A RequestedCollectionDate
    cannot settle before today, so the bank rejects the whole pain.008 batch —
    reject it at run creation instead of producing a doomed export."""

    code = "billing_run.invalid_collection_date"


class NoEligibleCharges(BadRequestError):
    """No PLANNED charges matched the run's period / payment method."""

    code = "billing_run.no_eligible_charges"


class NoValidSepaMandates(BadRequestError):
    """Charges were found, but none of their members have a SEPA-ready
    billing profile (valid mandate + IBAN + account holder)."""

    code = "billing_run.no_valid_mandates"


class BillingRunNotDraft(ConflictError):
    """Tried to export a run that is no longer DRAFT — a state conflict,
    not bad input. Re-exporting an EXPORTED run would re-issue charges."""

    code = "billing_run.not_draft"


class BillingRunHasNoCharges(BadRequestError):
    """A DRAFT run with zero attached charges can't be exported."""

    code = "billing_run.no_charges"


class SepaExportInvalid(BadRequestError):
    """The pain.008 XML can't be built because a required creditor or
    debtor field is missing. ``details`` carries the offending fields so
    the office UI can point the user at what to fix."""

    code = "sepa.export_invalid"


class BillingRunMixedCurrency(BadRequestError):
    """The eligible charges for a run span more than one currency, so
    ``total_amount`` would be a meaningless cross-currency sum. A billing run
    must be single-currency — reject up front rather than persist a nonsense
    figure (the export's per-charge EUR guard only fires for SEPA runs)."""

    code = "billing_run.mixed_currency"


class MandateReferenceLocked(BadRequestError):
    """The SEPA mandate reference can no longer be changed: the mandate has been
    used (``sepa_mandate_first_use_at`` is stamped), so every following
    collection goes out as RCUR under the reference the bank holds on file.
    Resubmitting the SAME reference is accepted; a different one needs a new
    mandate."""

    code = "billing_profile.mandate_reference_locked"


class IbanLocked(BadRequestError):
    """The IBAN can no longer be changed: the mandate has been used
    (``sepa_mandate_first_use_at`` is stamped), and the bank holds that mandate
    reference against the account the member authorised. Re-pointing a live
    mandate at another account is not an edit — it is a new mandate, so the
    office replaces the mandate (new reference for the new account) rather than
    swapping the IBAN underneath the old one. Resubmitting the SAME IBAN is
    accepted; the office SEPA form sends the whole mandate block back on every
    save."""

    code = "billing_profile.iban_locked"


class SepaMandateSignedInFuture(BadRequestError):
    """``sepa_mandate_signed_at`` lies in the future. A mandate cannot be signed
    after today, and such a value aborts the entire pain.008 batch at export
    time — for every other member in the run — so it is refused where it is
    entered."""

    code = "sepa.mandate_signed_in_future"


__all__ = [
    "BillingRunInvalidPeriod",
    "BillingRunInvalidCollectionDate",
    "NoEligibleCharges",
    "NoValidSepaMandates",
    "BillingRunNotDraft",
    "BillingRunHasNoCharges",
    "SepaExportInvalid",
    "BillingRunMixedCurrency",
    "MandateReferenceLocked",
    "IbanLocked",
    "SepaMandateSignedInFuture",
]
