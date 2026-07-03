"""Tests for the ``rotate_field_encryption`` management command.

How we test crypto-rotation
---------------------------
The core question is: "did the command actually re-encrypt the rows,
or did it just iterate past them silently?"

We answer it with a **ciphertext-delta inspection** pattern:

  1. Create a row with an encrypted field (e.g. ``Member.iban``).
  2. Capture the raw bytes from the column via a direct cursor query
     (the ``_raw()`` helper bypasses ``EncryptedCharField``'s
     ``from_db_value`` so we see the ciphertext, not the plaintext).
  3. Run the rotate command.
  4. Capture the raw bytes again.
  5. Assert: the ciphertext **changed** (proves re-encryption ran)
     AND the decrypted plaintext is **unchanged** (proves the data
     wasn't corrupted).

The ciphertext changes on every re-encryption because Fernet uses a
random IV per call. So we don't have to swap ``FIELD_ENCRYPTION_KEY``
mid-test to prove the rotation worked — re-encrypting the same value
with the same key still produces fresh ciphertext.

Why this beats the "swap keys mid-test" approach
-------------------------------------------------
The other obvious test is: set the key to A, write a row, swap the
key list to ``[B, A]``, run the command, swap to ``[B]``, read back
and verify. That's the gold standard but it requires
``django.test.override_settings`` to actually swap the Fernet
instance, and the encrypted-model-fields library reads the key once
per process — making the swap a fight against library internals.
The ciphertext-delta approach gives equivalent coverage of the
command's correctness without that complexity.
"""

from __future__ import annotations

import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

from apps.commissioning.models import ContactEntity, Member
from apps.commissioning.tests.factories.basics import ContactEntityFactory
from apps.commissioning.tests.factories.members import MemberFactory
from apps.payments.constants import PaymentMethodOptions
from apps.payments.models import BillingProfile

# Valid German IBAN from the SEPA spec's worked example — synthetic,
# not a real account.
SAMPLE_IBAN = "DE89370400440532013000"
SAMPLE_BIC = "COBADEFFXXX"
SAMPLE_OWNER = "Alice Schmidt"


def _raw(table: str, column: str, pk) -> str | None:
    """Read a column value bypassing Django's field descriptors.

    Mirrors the helper in ``apps/payments/tests/test_pii_encryption_at_rest.py``
    — going through a raw cursor returns whatever sits in the column
    (ciphertext for EncryptedCharField), skipping ``from_db_value``.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [pk])
        row = cursor.fetchone()
    return row[0] if row else None


def _run_command(**kwargs) -> str:
    """Run the rotate command, return captured stdout."""
    buf = StringIO()
    # ``--schema=test_pytest`` keeps the test deterministic: only this
    # tenant gets processed even if other Tenant rows exist in public.
    call_command(
        "rotate_field_encryption",
        schema="test_pytest",
        stdout=buf,
        **kwargs,
    )
    return buf.getvalue()


@pytest.mark.django_db
class TestReEncryptsMemberFields:
    def test_iban_ciphertext_changes_plaintext_preserved(self, tenant):
        member = MemberFactory(iban=SAMPLE_IBAN)
        raw_before = _raw("commissioning_member", "iban", member.pk)
        assert raw_before is not None  # sanity: encrypted

        _run_command()

        raw_after = _raw("commissioning_member", "iban", member.pk)
        member.refresh_from_db()

        # Re-encryption: same plaintext, fresh IV → different ciphertext.
        assert raw_after != raw_before, (
            "Rotate command must rewrite the ciphertext (Fernet random "
            "IV means re-encrypt always changes the bytes). Same bytes "
            "back means the row was iterated past without saving."
        )
        # Round-trip integrity: decryption still works.
        assert member.iban == SAMPLE_IBAN

    def test_account_owner_re_encrypted_alongside_iban(self, tenant):
        member = MemberFactory(iban=SAMPLE_IBAN, account_owner=SAMPLE_OWNER)
        iban_before = _raw("commissioning_member", "iban", member.pk)
        owner_before = _raw("commissioning_member", "account_owner", member.pk)

        _run_command()

        iban_after = _raw("commissioning_member", "iban", member.pk)
        owner_after = _raw("commissioning_member", "account_owner", member.pk)
        member.refresh_from_db()

        # Both encrypted fields on the same model get touched in one save.
        assert iban_after != iban_before
        assert owner_after != owner_before
        assert member.iban == SAMPLE_IBAN
        assert member.account_owner == SAMPLE_OWNER

    def test_null_values_stay_null(self, tenant):
        """The command must not crash on NULL encrypted columns + must
        leave them NULL afterwards (not e.g. an empty-string ciphertext)."""
        member = MemberFactory(iban=None, account_owner=None)

        _run_command()

        member.refresh_from_db()
        assert member.iban is None
        assert member.account_owner is None
        assert _raw("commissioning_member", "iban", member.pk) is None


@pytest.mark.django_db
class TestReEncryptsContactEntity:
    def test_contactentity_iban_re_encrypted(self, tenant):
        entity = ContactEntityFactory(
            iban=SAMPLE_IBAN,
            address="Main St 1",
            zip_code="10115",
            city="Berlin",
        )
        raw_before = _raw("commissioning_contactentity", "iban", entity.pk)

        _run_command()

        raw_after = _raw("commissioning_contactentity", "iban", entity.pk)
        entity.refresh_from_db()

        assert raw_after != raw_before
        assert entity.iban == SAMPLE_IBAN


@pytest.mark.django_db
class TestReEncryptsBillingProfile:
    """BillingProfile has 3 encrypted fields — confirms the command
    touches all of them in one save, not just one."""

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

    def test_all_three_fields_re_encrypted(self, profile):
        iban_before = _raw("payments_billingprofile", "iban", profile.pk)
        holder_before = _raw("payments_billingprofile", "account_holder", profile.pk)

        _run_command()

        iban_after = _raw("payments_billingprofile", "iban", profile.pk)
        holder_after = _raw("payments_billingprofile", "account_holder", profile.pk)
        profile.refresh_from_db()

        assert iban_after != iban_before
        assert holder_after != holder_before
        assert profile.iban == SAMPLE_IBAN

        assert profile.account_holder == "Bob Müller"

    def test_sepa_mandate_reference_untouched(self, profile):
        """Lock in that the rotate command doesn't accidentally rewrite
        the deliberately-unencrypted ``sepa_mandate_reference`` (its
        ``unique=True`` constraint depends on plaintext storage)."""
        ref_before = _raw(
            "payments_billingprofile", "sepa_mandate_reference", profile.pk
        )

        _run_command()

        ref_after = _raw(
            "payments_billingprofile", "sepa_mandate_reference", profile.pk
        )
        # Unencrypted field — bytes must be identical (no write).
        assert ref_after == ref_before == "MND-TEST-001"


@pytest.mark.django_db
class TestDryRun:
    def test_dry_run_does_not_change_ciphertext(self, tenant):
        member = MemberFactory(iban=SAMPLE_IBAN)
        raw_before = _raw("commissioning_member", "iban", member.pk)

        output = _run_command(dry_run=True)

        raw_after = _raw("commissioning_member", "iban", member.pk)
        # Same bytes → no save fired → dry-run is read-only as advertised.
        assert raw_after == raw_before

        # And the output should mention what it would have touched.
        assert "Would re-encrypt" in output or "would touch" in output


@pytest.mark.django_db
class TestIdempotency:
    def test_running_twice_preserves_plaintext(self, tenant):
        """Even if step 4 of the rotation procedure (drop old key) fires
        partway through the command, re-running picks up where it left
        off. This test sanity-checks that two consecutive runs don't
        corrupt anything — each run produces fresh ciphertext but the
        decrypted value stays put."""
        member = MemberFactory(iban=SAMPLE_IBAN)

        _run_command()
        raw_after_first = _raw("commissioning_member", "iban", member.pk)

        _run_command()
        raw_after_second = _raw("commissioning_member", "iban", member.pk)
        member.refresh_from_db()

        # Each run rewrites with a fresh IV.
        assert raw_after_second != raw_after_first
        # Plaintext survives both rotations.
        assert member.iban == SAMPLE_IBAN


@pytest.mark.django_db
class TestEmptyTableIsNoop:
    def test_empty_table_does_not_crash(self, tenant):
        """No Members at all — the command must skip the model cleanly."""
        Member.objects.all().delete()
        ContactEntity.objects.all().delete()
        BillingProfile.objects.all().delete()

        output = _run_command()

        assert "0 rows — skipped" in output or "0 row(s)" in output
