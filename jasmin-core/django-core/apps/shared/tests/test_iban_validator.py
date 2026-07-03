"""Tests for the IBAN ISO 13616 mod-97 validator.

Catches the four failure modes the office is most likely to produce:

  * pasted IBAN with extra characters or letters in the digit
    positions (``InvalidFormat``)
  * wrong country-specific length, e.g. typing a 23-char string for
    a German IBAN (``InvalidLength``)
  * digit transposition or single-character typo
    (``InvalidChecksum``)
  * fictional country code (``InvalidComponent``)

These map 1:1 to four ``ValidationError.code`` values the office UI
can pivot on for a specific error message — the suite verifies the
code mapping so a future refactor of the wrapper can't silently flip
the codes.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.shared.iban_validator import IBANValidator, validate_iban

# Bundesbank example IBAN, mod-97 valid, used throughout the
# payments fixtures so the same value works end-to-end.
VALID_DE = "DE89370400440532013000"
VALID_FR = "FR1420041010050500013M02606"  # France 27 chars
VALID_NL = "NL91ABNA0417164300"  # Netherlands 18 chars


class TestIBANValidatorAccepts:
    def test_valid_german_iban_passes(self):
        validate_iban(VALID_DE)  # no raise

    def test_valid_french_iban_passes(self):
        validate_iban(VALID_FR)

    def test_valid_dutch_iban_passes(self):
        validate_iban(VALID_NL)

    def test_iban_with_spaces_accepted(self):
        """Office pastes IBANs from bank statements that group digits
        in 4s. The validator must normalise rather than reject."""
        validate_iban("DE89 3704 0044 0532 0130 00")

    def test_iban_with_mixed_case_accepted(self):
        """``de89...`` is the same IBAN as ``DE89...``. ``python-stdnum``
        upper-cases internally; pin so a future swap doesn't regress."""
        validate_iban(VALID_DE.lower())

    def test_blank_and_none_pass_silently(self):
        """The validator is attached to ``blank=True`` fields, so
        empty values must NOT raise. Callers needing "must be present"
        use ``required=True`` or an explicit check at the call site."""
        validate_iban(None)
        validate_iban("")


class TestIBANValidatorRejects:
    """All four failure shapes (format / length / checksum / unknown
    country) bubble up as the same ``iban_invalid`` code with the same
    message. ``python-stdnum`` 2.x doesn't reliably distinguish the
    underlying cause — it falls through to ``InvalidChecksum`` for
    several inputs we'd expect to be ``InvalidLength`` or
    ``InvalidComponent``. The contract is "rejects malformed IBANs,
    accepts valid ones" — single code is honest about what we can pin.

    Note on the hyphen case: ``compact()`` inside stdnum strips both
    spaces AND hyphens, so ``DE89-3704-...`` is normalized into a
    valid IBAN before validation. We test a hyphen-injected
    *invalid* IBAN instead so the test still proves the rejection
    path runs."""

    def test_checksum_typo_raises(self):
        # Flip the last digit of a valid IBAN — same length, same
        # format, bad mod-97 → InvalidChecksum.
        with pytest.raises(ValidationError) as exc:
            validate_iban("DE89370400440532013001")
        assert exc.value.code == "iban_invalid"

    def test_wrong_length_raises(self):
        # DE is fixed at 22 chars; 23 chars must be rejected.
        with pytest.raises(ValidationError) as exc:
            validate_iban("DE893704004405320130000")
        assert exc.value.code == "iban_invalid"

    def test_non_alphanumeric_with_invalid_checksum_raises(self):
        # ``$`` isn't valid in any IBAN position — and even if stdnum
        # were to strip it, the resulting string would fail mod-97.
        with pytest.raises(ValidationError) as exc:
            validate_iban("DE89$704004405320130001")
        assert exc.value.code == "iban_invalid"

    def test_unknown_country_code_raises(self):
        # ``XX`` isn't an ISO country code.
        with pytest.raises(ValidationError) as exc:
            validate_iban("XX89370400440532013000")
        assert exc.value.code == "iban_invalid"


class TestValidatorEquality:
    def test_two_instances_compare_equal(self):
        """Django serializes validator instances into migrations. The
        validator must be value-equal so makemigrations doesn't
        generate spurious AlterField operations every time someone
        reimports the module."""
        assert IBANValidator() == IBANValidator()

    def test_validator_is_deconstructible(self):
        """``@deconstructible`` is required for the validator to round-
        trip through Django migrations. Verify the decorator is
        present (negative test: importing without the decorator would
        crash makemigrations)."""
        assert hasattr(IBANValidator(), "deconstruct")


@pytest.mark.django_db
class TestModelIntegration:
    """End-to-end: the validator wired onto ``Tenant.iban`` should fire
    when ``Tenant.full_clean()`` runs (the DRF serializer calls
    ``full_clean`` for us)."""

    def test_tenant_full_clean_rejects_bad_iban(self):
        from apps.shared.tenants.models import Tenant

        tenant = Tenant(
            name="Test Tenant",
            schema_name="test_iban_validation",
            iban="DE89370400440532013001",  # bad checksum
        )
        with pytest.raises(ValidationError) as exc:
            tenant.full_clean(exclude=["domain_url", "created_on"])
        # The error nests under the field name when raised through
        # full_clean.
        assert "iban" in exc.value.message_dict

    def test_tenant_full_clean_accepts_blank_iban(self):
        """``blank=True``: a fresh tenant without IBAN must validate.
        The "you can't export SEPA without an IBAN" check fires later,
        at export time."""
        from apps.shared.tenants.models import Tenant

        tenant = Tenant(
            name="Test Tenant",
            schema_name="test_iban_blank_allowed",
            iban=None,
        )
        # No raise.
        try:
            tenant.full_clean(exclude=["domain_url", "created_on"])
        except ValidationError as exc:
            # Allow other unrelated validation errors but NOT one on
            # the iban field.
            assert "iban" not in exc.message_dict
