"""Reseller / ContactEntity auditlog coverage — the B2B change history.

``Reseller`` and ``ContactEntity`` are auditlog-registered in
``commissioning/apps.py`` so edits to a reseller's invoice details or a
contact's name / email / phone / IBAN leave a GoBD / Art. 17 change trail —
and so the ``GDPRService._scrub_auditlog_entries`` Reseller/ContactEntity
scrub on anonymization acts on real rows instead of an empty set. PII columns
are masked (mirroring ``Member``) so the raw values never land in the
forever-retained change diffs.
"""

from __future__ import annotations

import pytest

from apps.commissioning.tests.factories import (
    ContactEntityFactory,
    ResellerFactory,
)


@pytest.mark.django_db
class TestResellerAuditlog:
    def test_reseller_edits_are_audited(self, tenant):
        from auditlog.models import LogEntry

        reseller = ResellerFactory()
        reseller.invoice_name = "Hof Müller GmbH"
        reseller.save()

        entries = LogEntry.objects.get_for_object(reseller)
        assert entries.exists(), (
            "Reseller saves should produce auditlog entries — is the "
            "auditlog registration in commissioning/apps.py gone?"
        )

    def test_reseller_invoice_address_is_masked(self, tenant):
        from auditlog.models import LogEntry

        reseller = ResellerFactory()
        reseller.invoice_address = "Geheimstrasse 1"
        reseller.save()

        entries = LogEntry.objects.get_for_object(reseller)
        blob = " ".join(str(entry.changes) for entry in entries)
        # The field is tracked (key present) but the raw value is masked.
        assert "invoice_address" in blob
        assert "Geheimstrasse 1" not in blob

    def test_contact_entity_edits_are_audited_and_iban_masked(self, tenant):
        from auditlog.models import LogEntry

        contact = ContactEntityFactory()
        contact.iban = "DE89370400440532013000"
        contact.email = "secret@example.org"
        contact.save()

        entries = LogEntry.objects.get_for_object(contact)
        assert entries.exists(), (
            "ContactEntity saves should produce auditlog entries — is the "
            "auditlog registration in commissioning/apps.py gone?"
        )
        blob = " ".join(str(entry.changes) for entry in entries)
        # PII never lands verbatim in the retained diffs.
        assert "DE89370400440532013000" not in blob
        assert "secret@example.org" not in blob
