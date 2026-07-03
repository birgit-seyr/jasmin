"""Member auditlog masking — PII must not land in change diffs.

``Member`` is auditlog-registered with ``mask_fields`` so the raw IBAN,
email, address etc. never reach ``auditlog_logentry.changes`` (which is
retained forever). ``birth_date`` is the statutory GenG date-of-birth —
PII_IMMEDIATE for erasure and special-category-adjacent — and was missing
from the mask list, so every Member create/edit wrote the plaintext DoB
into the audit table. This test pins it masked.
"""

from __future__ import annotations

import datetime

import pytest

from apps.commissioning.tests.factories import JasminUserFactory, MemberFactory


@pytest.mark.django_db
class TestMemberAuditlogMasking:
    def test_birth_date_is_masked_in_change_diffs(self, tenant):
        """Neither the old nor the new raw DoB may appear verbatim in the
        auditlog changes — both are masked. The field is still tracked
        (the key appears), just never in cleartext."""
        from auditlog.models import LogEntry

        user = JasminUserFactory()
        member = MemberFactory(user=user, birth_date=datetime.date(1985, 3, 14))
        # Produce an UPDATE diff carrying old + new DoB.
        member.birth_date = datetime.date(1990, 7, 2)
        member.save()

        entries = LogEntry.objects.get_for_object(member)
        assert entries.exists(), (
            "Member saves should produce auditlog entries — is the "
            "auditlog registration in commissioning/apps.py gone?"
        )
        blob = " ".join(str(entry.changes) for entry in entries)

        # The raw dates would appear verbatim if birth_date weren't masked.
        assert "1985-03-14" not in blob
        assert "1990-07-02" not in blob
        # ...but the field is still audited (just masked) — guards against
        # accidentally dropping birth_date from tracking entirely.
        assert "birth_date" in blob

    def test_iban_still_masked(self, tenant):
        """Sanity anchor: the pre-existing iban masking still holds, so a
        future mask_fields edit that breaks masking fails loudly here too."""
        from auditlog.models import LogEntry

        user = JasminUserFactory()
        member = MemberFactory(user=user)
        member.iban = "DE89370400440532013000"
        member.save()

        entries = LogEntry.objects.get_for_object(member)
        blob = " ".join(str(entry.changes) for entry in entries)
        assert "DE89370400440532013000" not in blob
