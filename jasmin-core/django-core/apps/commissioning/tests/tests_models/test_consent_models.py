"""Tests for the ConsentDocument + ConsentRecord model invariants.

DSGVO Art. 7(1) says the controller must demonstrate WHAT was agreed
to. These tests lock in the structural guarantees that make that
demonstrable:

  - ``body_sha256`` is auto-computed on save and matches the body
    byte-for-byte. Drift between body and hash = silent tampering.
  - ``TimeBoundMixin`` auto-succession: publishing a new version
    closes the predecessor's ``valid_until`` so at most one
    ConsentDocument per ``(kind, locale)`` is active at any moment.
  - The Monday/Sunday week-boundary check is intentionally bypassed
    for ConsentDocument — legal text goes live on whatever day the
    lawyers say, not on Mondays.
  - PROTECT relationships: deleting a ConsentDocument that has at
    least one ConsentRecord pointing at it raises ProtectedError.
    Deleting a Member with ConsentRecords does the same.
"""

from __future__ import annotations

import datetime
import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from apps.commissioning.models import (
    ConsentDocument,
    ConsentKind,
    ConsentRecord,
)
from apps.commissioning.tests.factories import MemberFactory

# --------------------------------------------------------------------------- #
# body_sha256 auto-compute                                                    #
# --------------------------------------------------------------------------- #


class TestBodySha256:
    def test_hash_is_computed_on_create(self, tenant):
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="hello world",
        )
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert doc.body_sha256 == expected

    def test_hash_updates_when_body_changes(self, tenant):
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="original",
        )
        original_hash = doc.body_sha256

        doc.body = "tampered"
        doc.save()

        assert doc.body_sha256 != original_hash
        assert doc.body_sha256 == hashlib.sha256(b"tampered").hexdigest()

    def test_empty_body_is_rejected_by_full_clean(self, tenant):
        """``body = TextField()`` (no ``blank=True``) — an empty body
        is rejected by ``full_clean``, which ``TimeBoundMixin.save``
        runs before every save. A consent document with no text would
        be meaningless to a member; pinning this prevents a future
        accidental ``blank=True`` from quietly enabling it."""
        with pytest.raises(ValidationError) as exc_info:
            ConsentDocument.objects.create(
                kind=ConsentKind.PRIVACY,
                locale="de",
                version="v1",
                valid_from=datetime.date(2026, 1, 1),
                body="",
            )
        assert "body" in exc_info.value.message_dict

    def test_unicode_body_hashed_via_utf8(self, tenant):
        """Implementation detail worth pinning: ``hashlib.sha256`` is
        fed UTF-8 bytes. If someone ever switches to latin-1 by
        mistake, every multilingual body's hash changes silently."""
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="Datenschutzerklärung — Ü",
        )
        expected = hashlib.sha256("Datenschutzerklärung — Ü".encode()).hexdigest()
        assert doc.body_sha256 == expected


# --------------------------------------------------------------------------- #
# TimeBoundMixin: auto-succession + Monday-skip                               #
# --------------------------------------------------------------------------- #


class TestTimeBoundIntegration:
    def test_publishing_a_new_version_closes_the_predecessor(self, tenant):
        """Auto-succession in ``TimeBoundMixin.save`` closes the
        currently-open row in the same overlap group (``(kind,
        locale)``). The predecessor's ``valid_until`` is set to the
        day before the new ``valid_from``."""
        v1 = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="old text",
        )
        assert v1.valid_until is None

        ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v2",
            valid_from=datetime.date(2026, 3, 1),
            body="new text",
        )

        v1.refresh_from_db()
        assert v1.valid_until == datetime.date(2026, 2, 28)

    def test_different_locale_does_not_close_predecessor(self, tenant):
        """The overlap group includes ``locale`` — a German privacy
        v2 must not close the English privacy v1."""
        v1_de = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="de v1",
        )
        ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="en",
            version="v1",
            valid_from=datetime.date(2026, 3, 1),
            body="en v1",
        )

        v1_de.refresh_from_db()
        assert v1_de.valid_until is None  # untouched

    def test_different_kind_does_not_close_predecessor(self, tenant):
        privacy = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="privacy",
        )
        ConsentDocument.objects.create(
            kind=ConsentKind.SEPA,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 3, 1),
            body="sepa",
        )

        privacy.refresh_from_db()
        assert privacy.valid_until is None

    def test_valid_from_can_be_any_weekday(self, tenant):
        """``ConsentDocument.clean()`` overrides ``TimeBoundMixin`` to
        skip the Monday-only check. A Wednesday ``valid_from`` must
        save without raising."""
        wednesday = datetime.date(2026, 5, 20)
        assert wednesday.weekday() == 2  # confirm fixture is a Wednesday

        ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=wednesday,
            body="legal text",
        )
        # No ValidationError — pass.

    def test_valid_until_before_valid_from_is_rejected(self, tenant):
        """``ConsentDocument.clean`` calls
        ``TimeBoundMixin.validate_date_range``, which rejects
        ``valid_until < valid_from``. The same check ALSO has a
        ``CheckConstraint`` declared in the mixin's abstract Meta as
        belt-and-suspenders for raw-SQL paths — but app-level is the
        layer we hit first and the one the UI sees, so assert there.
        """
        with pytest.raises(ValidationError):
            ConsentDocument.objects.create(
                kind=ConsentKind.PRIVACY,
                locale="de",
                version="v1",
                valid_from=datetime.date(2026, 5, 20),
                valid_until=datetime.date(2026, 1, 1),
                body="text",
            )


# --------------------------------------------------------------------------- #
# Append-only: PROTECT on ConsentRecord FKs                                   #
# --------------------------------------------------------------------------- #


class TestProtectedDeletion:
    def test_cannot_delete_document_with_consent_records(self, tenant):
        member = MemberFactory()
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        ConsentRecord.objects.create(member=member, document=doc)

        with pytest.raises(ProtectedError):
            doc.delete()

    def test_can_delete_document_with_no_records(self, tenant):
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        doc.delete()
        assert not ConsentDocument.objects.filter(pk=doc.pk).exists()

    def test_cannot_delete_member_with_consent_records(self, tenant):
        """Member.consents is on_delete=PROTECT — anonymising an
        ex-member must NULL their PII fields, not DELETE the row.
        The PROTECT enforces that the audit trail outlives the
        person (DSGVO Art. 17 vs tax-law retention tension)."""
        member = MemberFactory()
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        ConsentRecord.objects.create(member=member, document=doc)

        with pytest.raises(ProtectedError):
            member.delete()


# --------------------------------------------------------------------------- #
# Properties + __str__                                                        #
# --------------------------------------------------------------------------- #


class TestConsentRecordProperties:
    def test_is_active_true_when_not_revoked(self, tenant):
        member = MemberFactory()
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        record = ConsentRecord.objects.create(member=member, document=doc)
        assert record.is_active is True

    def test_is_active_false_after_revoke(self, tenant):
        from django.utils import timezone

        member = MemberFactory()
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        now = timezone.now()
        record = ConsentRecord.objects.create(
            member=member,
            document=doc,
            consented_at=now - datetime.timedelta(days=1),
            revoked_at=now,
        )
        assert record.is_active is False

    def test_document_str_includes_kind_version_locale(self, tenant):
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.SEPA,
            locale="en",
            version="3.1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        assert str(doc) == "sepa/3.1/en"

    def test_record_str_reflects_active_vs_revoked_state(self, tenant):
        from django.utils import timezone

        member = MemberFactory()
        doc = ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="text",
        )
        active = ConsentRecord.objects.create(member=member, document=doc)
        assert "active" in str(active)

        now = timezone.now()
        revoked = ConsentRecord.objects.create(
            member=member,
            document=doc,
            consented_at=now - datetime.timedelta(days=1),
            revoked_at=now,
        )
        assert "revoked" in str(revoked)


# --------------------------------------------------------------------------- #
# Unique constraint                                                           #
# --------------------------------------------------------------------------- #


class TestUniqueConstraint:
    def test_cannot_create_two_documents_with_same_kind_version_locale(self, tenant):
        """``(kind, version, locale)`` is unique. Django's
        ``full_clean`` (run from ``TimeBoundMixin.save``) catches the
        duplicate via ``validate_unique`` BEFORE it reaches the DB,
        so the exception is a structured ``ValidationError`` rather
        than ``IntegrityError`` — better UX (per-field error) and the
        DB constraint is still there as belt-and-suspenders for
        bulk_create / raw SQL paths.
        """
        ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="first",
        )
        with pytest.raises(ValidationError):
            ConsentDocument.objects.create(
                kind=ConsentKind.PRIVACY,
                locale="de",
                version="v1",  # same triple
                valid_from=datetime.date(2026, 6, 1),
                body="duplicate",
            )

    def test_same_version_different_locale_is_allowed(self, tenant):
        ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="de",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="de",
        )
        ConsentDocument.objects.create(
            kind=ConsentKind.PRIVACY,
            locale="en",
            version="v1",
            valid_from=datetime.date(2026, 1, 1),
            body="en",
        )
        assert (
            ConsentDocument.objects.filter(
                kind=ConsentKind.PRIVACY, version="v1"
            ).count()
            == 2
        )
