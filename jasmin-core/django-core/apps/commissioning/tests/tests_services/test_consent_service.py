"""Tests for ConsentService.

Covers the contract the rest of the consent system depends on:

  - ``record`` creates a ConsentRecord AND keeps the denormalised
    cache column on Member in lock-step.
  - ``revoke`` flips ``revoked_at`` AND recomputes the cache to the
    next-still-active record (or NULL).
  - ``get_current_document`` returns the active row for a (kind,
    locale) pair, picks the latest ``valid_from`` when several are
    eligible, and raises a clean 404 when none are.

These are audit-critical paths — a silent regression here is a
DSGVO finding that compounds with every new signup until someone
notices.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from apps.commissioning.errors import (
    ConsentAlreadyRevoked,
    ConsentDocumentNotFound,
)
from apps.commissioning.models import (
    ConsentDocument,
    ConsentKind,
    ConsentRecord,
    Member,
)
from apps.commissioning.services import ConsentService
from apps.commissioning.tests.factories import MemberFactory

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_document(
    *,
    kind: str = ConsentKind.PRIVACY,
    locale: str = "de",
    version: str = "v1",
    valid_from: datetime.date | None = None,
    valid_until: datetime.date | None = None,
    body: str = "We process your data lawfully.",
) -> ConsentDocument:
    """Create a ConsentDocument bypassing TimeBoundMixin's overlap
    auto-succession — we want full control over (valid_from,
    valid_until) for the tests below."""
    doc = ConsentDocument(
        kind=kind,
        locale=locale,
        version=version,
        valid_from=valid_from or datetime.date(2026, 1, 1),
        valid_until=valid_until,
        body=body,
    )
    # Skip auto-succession by using the parent Model.save() — the
    # mixin's save() would close any predecessor automatically, which
    # we don't want when we're constructing precise scenarios.
    from django.db.models import Model

    doc.body_sha256 = ""  # populated by ConsentDocument.save normally
    # Recreate ConsentDocument.save's hash step without triggering the
    # mixin's full_clean / handle_succession.
    import hashlib

    doc.body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    Model.save(doc)
    return doc


# --------------------------------------------------------------------------- #
# get_current_document                                                        #
# --------------------------------------------------------------------------- #


class TestGetCurrentDocument:
    def test_returns_the_active_document_for_kind_and_locale(self, tenant):
        doc = _make_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            valid_from=datetime.date(2026, 1, 1),
        )
        found = ConsentService.get_current_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            as_of=datetime.date(2026, 6, 1),
        )
        assert found.pk == doc.pk

    def test_picks_the_latest_valid_from_when_multiple_active(self, tenant):
        """If by accident two documents are both "active" right now
        (overlap_unique_fields would normally prevent this, but raw
        SQL or a future bug could), the service must still return
        exactly one row — the latest by ``valid_from``."""
        _make_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="old",
            valid_from=datetime.date(2026, 1, 1),
        )
        newer = _make_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="new",
            valid_from=datetime.date(2026, 3, 1),
        )
        found = ConsentService.get_current_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            as_of=datetime.date(2026, 6, 1),
        )
        assert found.pk == newer.pk

    def test_skips_documents_that_have_been_superseded(self, tenant):
        """A row with ``valid_until`` in the past must NOT be returned
        even though it once was active."""
        _make_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="old",
            valid_from=datetime.date(2026, 1, 1),
            valid_until=datetime.date(2026, 2, 28),
        )
        newer = _make_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="new",
            valid_from=datetime.date(2026, 3, 1),
        )
        found = ConsentService.get_current_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            as_of=datetime.date(2026, 6, 1),
        )
        assert found.pk == newer.pk

    def test_skips_documents_that_are_not_yet_in_force(self, tenant):
        """``valid_from`` in the future is not active *now*."""
        _make_document(
            kind=ConsentKind.PRIVACY,
            locale="de",
            valid_from=datetime.date(2027, 1, 1),
        )
        with pytest.raises(ConsentDocumentNotFound):
            ConsentService.get_current_document(
                kind=ConsentKind.PRIVACY,
                locale="de",
                as_of=datetime.date(2026, 6, 1),
            )

    def test_raises_when_no_document_exists_for_kind_locale(self, tenant):
        # Privacy/de exists; SEPA/de does not.
        _make_document(kind=ConsentKind.PRIVACY, locale="de")
        with pytest.raises(ConsentDocumentNotFound):
            ConsentService.get_current_document(kind=ConsentKind.SEPA, locale="de")

    def test_locale_filter_is_strict(self, tenant):
        _make_document(kind=ConsentKind.PRIVACY, locale="de")
        with pytest.raises(ConsentDocumentNotFound):
            ConsentService.get_current_document(kind=ConsentKind.PRIVACY, locale="en")


# --------------------------------------------------------------------------- #
# record                                                                      #
# --------------------------------------------------------------------------- #


class TestRecord:
    def test_creates_consent_record_with_audit_fields(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)

        record = ConsentService.record(
            member=member,
            document=doc,
            ip_address="203.0.113.7",
            user_agent="Mozilla/5.0",
        )

        assert record.pk is not None
        assert record.member_id == member.pk
        assert record.document_id == doc.pk
        assert record.ip_address == "203.0.113.7"
        assert record.user_agent == "Mozilla/5.0"
        assert record.revoked_at is None
        assert record.consented_at is not None

    def test_updates_member_cache_column_for_known_kind(self, tenant):
        member = MemberFactory()
        assert member.privacy_consent is None

        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        member.refresh_from_db()
        assert member.privacy_consent is not None
        assert member.privacy_consent == record.consented_at

    def test_sepa_kind_updates_sepa_consent_column(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.SEPA)

        ConsentService.record(member=member, document=doc)

        member.refresh_from_db()
        assert member.sepa_consent is not None

    def test_withdrawal_kind_updates_withdrawal_consent_column(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.WITHDRAWAL)

        ConsentService.record(member=member, document=doc)

        member.refresh_from_db()
        assert member.withdrawal_consent is not None

    def test_unmapped_kind_creates_record_without_touching_cache(self, tenant):
        """``terms`` kind has no Member cache column — recording it
        should still succeed without raising. This is the "no
        _CACHE_FIELD_BY_KIND entry" branch in _sync_member_cache."""
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.TERMS)

        record = ConsentService.record(member=member, document=doc)

        assert record.pk is not None
        # None of the legacy cache columns gets touched.
        member.refresh_from_db()
        assert member.privacy_consent is None
        assert member.sepa_consent is None
        assert member.withdrawal_consent is None

    def test_truncates_user_agent_to_500_chars(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        very_long_ua = "x" * 1000

        record = ConsentService.record(
            member=member, document=doc, user_agent=very_long_ua
        )

        assert len(record.user_agent) == 500

    def test_ip_address_optional_for_paper_signed_consents(self, tenant):
        """Office staff entering a paper-signed consent on behalf of
        an offline member won't have an IP. The schema allows NULL and
        the service must pass it through."""
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)

        record = ConsentService.record(member=member, document=doc)

        assert record.ip_address is None


# --------------------------------------------------------------------------- #
# revoke                                                                      #
# --------------------------------------------------------------------------- #


class TestRevoke:
    def test_sets_revoked_at_and_reason(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        before = timezone.now()
        revoked = ConsentService.revoke(record, reason="user changed mind")
        after = timezone.now()

        assert revoked.revoked_at is not None
        assert before <= revoked.revoked_at <= after
        assert revoked.revoked_reason == "user changed mind"

    def test_clears_member_cache_when_no_active_consent_remains(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        member.refresh_from_db()
        assert member.privacy_consent is not None  # baseline

        ConsentService.revoke(record)

        member.refresh_from_db()
        assert member.privacy_consent is None

    def test_revoking_sepa_consent_stops_direct_debit(self, tenant):
        """GDPR-CON-1 (Art. 7(3)): withdrawing the SEPA mandate consent must
        switch the member's BillingProfile off SEPA Direct Debit so no future
        run auto-debits them. Wired via the apps.shared.sepa_mandate_hooks seam
        (payments registers the handler in AppConfig.ready())."""
        from apps.payments.constants import PaymentMethodOptions
        from apps.payments.models import BillingProfile

        member = MemberFactory()
        profile = BillingProfile.objects.create(
            member=member,
            payment_method=PaymentMethodOptions.SEPA_DIRECT_DEBIT,
            iban="DE89370400440532013000",
            account_holder="Anna Member",
            sepa_mandate_reference="MND-REVOKE-1",
            sepa_mandate_signed_at=datetime.date(2026, 1, 5),
            is_active=True,
        )
        doc = _make_document(kind=ConsentKind.SEPA)
        record = ConsentService.record(member=member, document=doc)

        ConsentService.revoke(record, reason="withdrawn")

        profile.refresh_from_db()
        assert profile.payment_method == PaymentMethodOptions.BANK_TRANSFER

    def test_cache_rolls_back_to_next_active_record(self, tenant):
        """Two consents for the same kind: revoking the LATER one
        should drop the cache back to the earlier one (not to NULL)."""
        member = MemberFactory()
        doc1 = _make_document(kind=ConsentKind.PRIVACY, version="v1", locale="de")
        doc2 = _make_document(
            kind=ConsentKind.PRIVACY,
            version="v2",
            locale="en",  # different locale to skip overlap check
        )
        record1 = ConsentService.record(member=member, document=doc1)
        record2 = ConsentService.record(member=member, document=doc2)
        member.refresh_from_db()
        baseline = member.privacy_consent
        assert baseline == record2.consented_at  # the later one wins

        ConsentService.revoke(record2)

        member.refresh_from_db()
        assert member.privacy_consent == record1.consented_at

    def test_raises_consent_already_revoked_on_double_revoke(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        ConsentService.revoke(record)
        with pytest.raises(ConsentAlreadyRevoked):
            ConsentService.revoke(record, reason="oops")

    def test_records_revoked_by_when_provided(self, tenant, user):
        """``user`` fixture is an office-role JasminUser — same one
        every other tenant-scoped test uses."""
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        revoked = ConsentService.revoke(record, revoked_by=user)

        assert revoked.revoked_by_id == user.pk

    def test_truncates_revoked_reason_to_200_chars(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        revoked = ConsentService.revoke(record, reason="x" * 500)

        assert len(revoked.revoked_reason) == 200


# --------------------------------------------------------------------------- #
# Cache integrity edge cases                                                  #
# --------------------------------------------------------------------------- #


class TestCacheIntegrity:
    def test_revoking_one_kind_does_not_clear_other_kinds_cache(self, tenant):
        member = MemberFactory()
        privacy_doc = _make_document(kind=ConsentKind.PRIVACY)
        sepa_doc = _make_document(kind=ConsentKind.SEPA)

        ConsentService.record(member=member, document=privacy_doc)
        sepa_record = ConsentService.record(member=member, document=sepa_doc)

        member.refresh_from_db()
        assert member.privacy_consent is not None
        assert member.sepa_consent is not None

        ConsentService.revoke(sepa_record)

        member.refresh_from_db()
        # SEPA cleared, privacy untouched.
        assert member.sepa_consent is None
        assert member.privacy_consent is not None

    def test_record_then_revoke_leaves_only_the_record_row_behind(self, tenant):
        """``ConsentRecord`` is the append-only audit table — revoking
        must NOT delete the row; it must remain queryable for audit."""
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        ConsentService.revoke(record, reason="testing")

        rows = ConsentRecord.objects.filter(member=member)
        assert rows.count() == 1
        revoked = rows.first()
        assert revoked.pk == record.pk
        assert revoked.revoked_at is not None
        assert revoked.revoked_reason == "testing"
        assert revoked.is_active is False

    def test_member_factory_starts_with_no_consents(self, tenant):
        """Sanity check on the test fixture so the cache-update tests
        above are actually testing a transition (not a no-op)."""
        member = MemberFactory()
        assert member.privacy_consent is None
        assert member.sepa_consent is None
        assert member.withdrawal_consent is None
        assert not Member.objects.filter(
            pk=member.pk, privacy_consent__isnull=False
        ).exists()


# --------------------------------------------------------------------------- #
# Withdrawal → office review (privacy / withdrawal-terms consent)             #
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
class TestConsentWithdrawalReview:
    """Withdrawing a privacy / withdrawal-terms consent flags the member for
    office review AND queues an office email; re-consent clears the flag.
    TERMS (not a processing legal basis) does neither."""

    def test_revoke_privacy_flags_member_and_queues_office_email(
        self, tenant, django_capture_on_commit_callbacks
    ):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        record = ConsentService.record(member=member, document=doc)

        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            ConsentService.revoke(record)

        member.refresh_from_db()
        assert member.consent_withdrawn_at is not None
        # The office-alert email is queued to fire on commit (mail_admins).
        assert len(callbacks) == 1

    def test_reconsent_clears_the_review_flag(self, tenant):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.PRIVACY)
        first = ConsentService.record(member=member, document=doc)
        ConsentService.revoke(first)
        member.refresh_from_db()
        assert member.consent_withdrawn_at is not None

        ConsentService.record(member=member, document=doc)
        member.refresh_from_db()
        assert member.consent_withdrawn_at is None

    def test_revoke_terms_does_not_flag_or_email(
        self, tenant, django_capture_on_commit_callbacks
    ):
        member = MemberFactory()
        doc = _make_document(kind=ConsentKind.TERMS)
        record = ConsentService.record(member=member, document=doc)

        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            ConsentService.revoke(record)

        member.refresh_from_db()
        assert member.consent_withdrawn_at is None
        assert len(callbacks) == 0
