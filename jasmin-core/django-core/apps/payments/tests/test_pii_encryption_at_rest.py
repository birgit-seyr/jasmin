"""Verify Fernet encryption-at-rest on bank-account PII.

The contract this test enforces:

  1. ORM round-trip is transparent — callers see plaintext on both
     read and write, with no API changes from the unencrypted era.
  2. The database column stores ciphertext, not plaintext —
     ``pg_dump`` / raw SQL access yields encrypted bytes only.
  3. Same plaintext re-encrypted yields *different* ciphertext
     (Fernet uses a random IV). This matters: an attacker with raw
     DB access must not be able to correlate members by spotting
     identical ciphertext for the same shared IBAN.
  4. ``BillingProfile.sepa_mandate_reference`` is deliberately NOT
     encrypted (so its ``unique=True`` constraint still works) —
     locked in by a complementary test below.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import connection

from apps.commissioning.models import ContactEntity, Member
from apps.commissioning.tests.factories.basics import ContactEntityFactory
from apps.commissioning.tests.factories.members import MemberFactory
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile

# Valid German IBAN from the SEPA spec's worked example — safe to
# hardcode (synthetic, not a real account).
SAMPLE_IBAN = "DE89370400440532013000"


def _raw(table: str, column: str, pk) -> str | None:
    """Read a column value bypassing Django's field descriptors.

    EncryptedCharField decrypts on the way out via ``from_db_value``;
    going through ``cursor.execute`` instead returns whatever sits in
    the column — ciphertext if the field is encrypted, plaintext if
    not.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [pk])
        row = cursor.fetchone()
    return row[0] if row else None


class TestMemberBankFieldsEncryption:
    def test_iban_roundtrip_returns_plaintext(self, tenant):
        member = MemberFactory(iban=SAMPLE_IBAN, account_owner="Alice Schmidt")
        member.refresh_from_db()
        assert member.iban == SAMPLE_IBAN
        assert member.account_owner == "Alice Schmidt"

    def test_iban_stored_as_ciphertext(self, tenant):
        member = MemberFactory(iban=SAMPLE_IBAN)
        raw_iban = _raw("commissioning_member", "iban", member.pk)
        assert raw_iban is not None
        assert raw_iban != SAMPLE_IBAN
        # Defence in depth: even a substring of the plaintext must
        # not appear in the ciphertext.
        assert "DE89" not in raw_iban

    def test_account_owner_stored_as_ciphertext(self, tenant):
        member = MemberFactory(account_owner="Alice Schmidt")
        raw = _raw("commissioning_member", "account_owner", member.pk)
        assert raw is not None
        assert raw != "Alice Schmidt"
        assert "Schmidt" not in raw

    def test_same_iban_yields_different_ciphertext(self, tenant):
        m1 = MemberFactory(iban=SAMPLE_IBAN)
        m2 = MemberFactory(iban=SAMPLE_IBAN)
        c1 = _raw("commissioning_member", "iban", m1.pk)
        c2 = _raw("commissioning_member", "iban", m2.pk)
        assert c1 != c2, (
            "Fernet must use a random IV per encryption — otherwise an "
            "attacker with raw DB access can group members by IBAN."
        )

    def test_null_iban_stays_null(self, tenant):
        """No spurious encryption of NULL values — the column must
        still allow NULL after the alter, and reading it back yields
        None, not an empty ciphertext."""
        member = MemberFactory(iban=None)
        member.refresh_from_db()
        assert member.iban is None
        assert _raw("commissioning_member", "iban", member.pk) is None


class TestContactEntityIbanEncryption:
    def test_iban_roundtrip(self, tenant):
        entity = ContactEntityFactory(
            iban=SAMPLE_IBAN, address="Main St 1", zip_code="10115", city="Berlin"
        )
        entity.refresh_from_db()
        assert entity.iban == SAMPLE_IBAN

    def test_iban_stored_as_ciphertext(self, tenant):
        entity = ContactEntityFactory(
            iban=SAMPLE_IBAN, address="Main St 1", zip_code="10115", city="Berlin"
        )
        raw = _raw("commissioning_contactentity", "iban", entity.pk)
        assert raw is not None
        assert raw != SAMPLE_IBAN


class TestBillingProfileBankFieldsEncryption:
    @pytest.fixture
    def profile(self, tenant):
        member = MemberFactory(first_name="Bob", last_name="Müller")
        return BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban=SAMPLE_IBAN,
            account_holder="Bob Müller",
            sepa_mandate_reference="MND-TEST-001",
            sepa_mandate_signed_at=datetime.date(2026, 1, 1),
            is_active=True,
        )

    def test_iban_account_holder_roundtrip(self, profile):
        profile.refresh_from_db()
        assert profile.iban == SAMPLE_IBAN
        assert profile.account_holder == "Bob Müller"

    def test_iban_stored_as_ciphertext(self, profile):
        raw = _raw("payments_billingprofile", "iban", profile.pk)
        assert raw != SAMPLE_IBAN
        assert "DE89" not in raw

    def test_account_holder_stored_as_ciphertext(self, profile):
        raw = _raw("payments_billingprofile", "account_holder", profile.pk)
        assert raw != "Bob Müller"
        assert "Müller" not in raw

    def test_sepa_mandate_reference_is_NOT_encrypted(self, profile):
        """Lock in the deliberate decision to leave mandate reference
        plaintext: encrypting it would silently break ``unique=True``.
        If a future refactor encrypts it, this test fails loudly so
        the uniqueness regression doesn't ship unnoticed.
        """
        raw = _raw("payments_billingprofile", "sepa_mandate_reference", profile.pk)
        assert raw == "MND-TEST-001"


class TestEncryptedFieldsRejectQueryByValue:
    """Document — by way of a test — that encrypted columns cannot be
    filtered by plaintext value. Fernet's random IV means
    ``Model.objects.filter(iban=SAMPLE_IBAN)`` matches zero rows even
    when a row with that IBAN exists. Any code that needs IBAN lookup
    must query by member/profile FK instead.
    """

    def test_filter_by_encrypted_iban_returns_nothing(self, tenant):
        MemberFactory(iban=SAMPLE_IBAN)
        assert Member.objects.filter(iban=SAMPLE_IBAN).count() == 0

    def test_filter_by_encrypted_contactentity_iban_returns_nothing(self, tenant):
        ContactEntityFactory(
            iban=SAMPLE_IBAN, address="Main St 1", zip_code="10115", city="Berlin"
        )
        assert ContactEntity.objects.filter(iban=SAMPLE_IBAN).count() == 0
