"""IBAN well-formedness validator.

Reusable Django field validator that runs the ISO 13616 mod-97 check
against any candidate IBAN string. Catches typos and transpositions —
does NOT verify that the IBAN points at a real, open bank account
(that would require an off-platform check at submission time).

Wired through ``python-stdnum`` (an already-transitive dependency of
``sepaxml``) so we don't re-implement the country-length table or the
mod-97 algorithm.

Empty strings and ``None`` pass through silently: ``blank=True``
fields stay legitimately blank without this validator forcing the
office to fill them. Callers that need "must be present" use the
existing ``required`` flag or a separate check at the call site
(e.g. ``apps/payments/services.py`` raises if a SEPA export can't
find a creditor IBAN).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _
from stdnum.exceptions import ValidationError as StdnumValidationError
from stdnum.iban import validate as _stdnum_validate


@deconstructible
class IBANValidator:
    """Validates IBAN well-formedness via mod-97 + country-length check.

    Raises ``django.core.exceptions.ValidationError`` with the single
    stable code ``iban_invalid``. Earlier versions of this validator
    tried to distinguish the four ``python-stdnum`` failure modes
    (format / length / checksum / component) into separate codes, but
    stdnum 2.x's ordering is conservative — it raises ``InvalidChecksum``
    for several inputs where the actual cause is the length or country.
    A single code + message keeps the validator's contract stable
    across stdnum versions and is honest about what we can actually
    distinguish.
    """

    message = _(
        "Enter a valid IBAN. Check the country code, the length (e.g. "
        "DE = 22 characters, AT = 20, CH = 21), and the check digits "
        "for typos."
    )

    def __call__(self, value) -> None:
        if value in (None, ""):
            return
        # Office often pastes IBANs with spaces from bank statements.
        # ``python-stdnum`` accepts both but normalising here makes the
        # rejection deterministic regardless of input formatting.
        candidate = "".join(str(value).split())
        try:
            _stdnum_validate(candidate)
        except StdnumValidationError as exc:
            # Catch any of the stdnum ``ValidationError`` subclasses
            # (InvalidFormat, InvalidLength, InvalidChecksum,
            # InvalidComponent). They all map to the same office-facing
            # message — see the docstring above for why.
            raise DjangoValidationError(self.message, code="iban_invalid") from exc

    def __eq__(self, other) -> bool:
        return isinstance(other, IBANValidator)


# Re-exported as a module-level instance because Django expects
# validators in ``validators=[...]`` to be callables, and importing a
# pre-instantiated object keeps the model-field declaration tidy.
validate_iban = IBANValidator()
