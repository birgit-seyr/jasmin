"""Tests for the ``replay_gdpr_deletions`` management command.

A backup restore brings back the personal data of everyone erased after the
backup was taken, and rolls back the deletion log that recorded those
erasures with it. The command reads the copy of the log kept outside the
database (the ledger ``backups/backup.sh ledger`` writes) and erases them
again.

The state these tests build is the one a restore leaves behind: the subject
is back with its personal data, the database has no log row for the erasure,
and only the ledger still knows about it.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from apps.authz.roles import Role
from apps.commissioning.tests.factories import (
    CoopShareFactory,
    JasminUserFactory,
    MemberFactory,
    ResellerFactory,
)
from apps.gdpr.management.commands.replay_gdpr_deletions import (
    email_sha256,
    read_ledger,
)
from apps.gdpr.models import DeletionLog
from apps.gdpr.services import GDPRService

BACKUP_SH = Path(__file__).resolve().parents[5] / "backups" / "backup.sh"


def _entry(tenant, log_id: str, **keys) -> dict:
    """A ledger line as ``backup.sh`` writes it, for an erasure made after
    the backup (so the restored database has no row for ``log_id``)."""
    return {
        "schema": tenant.schema_name,
        "id": log_id,
        "deleted_at": keys.pop(
            "deleted_at", (timezone.now() - datetime.timedelta(hours=1)).isoformat()
        ),
        "user_pk": keys.pop("user_pk", ""),
        "member_pk": keys.pop("member_pk", ""),
        "reseller_pk": keys.pop("reseller_pk", ""),
        "email_sha256": keys.pop("email_sha256", None),
    }


def _ledger(tmp_path, *entries: dict) -> str:
    path = tmp_path / "gdpr-deletion-ledger.jsonl"
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    return str(path)


def _replay(ledger: str, *flags: str) -> str:
    out = io.StringIO()
    call_command("replay_gdpr_deletions", "--ledger", ledger, *flags, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestReplayAfterRestore:
    def test_erases_a_restored_member_and_writes_its_log_row_back(
        self, tenant, tmp_path
    ):
        user = JasminUserFactory(email="restored@example.com", first_name="Restored")
        member = MemberFactory(
            user=user, first_name="Restored", address="Hauptstrasse 1"
        )
        entry = _entry(tenant, "LoGaFtErBaK1", user_pk=user.pk, member_pk=member.pk)

        output = _replay(_ledger(tmp_path, entry))

        user.refresh_from_db()
        member.refresh_from_db()
        assert user.email.endswith("@deleted.invalid")
        assert user.is_active is False
        assert member.first_name == "Gelöscht"
        assert member.address is None
        # The restored database records the erasure again, under its original
        # id and time, and no second row for it.
        log = DeletionLog.objects.get(pk="LoGaFtErBaK1")
        assert (
            log.deleted_at.isoformat()
            == datetime.datetime.fromisoformat(entry["deleted_at"]).isoformat()
        )
        assert (log.user_pk, log.member_pk) == (user.pk, member.pk)
        assert DeletionLog.objects.filter(member_pk=member.pk).count() == 1
        assert "1 erased again" in output

    def test_erases_a_member_without_a_login(self, tenant, tmp_path):
        member = MemberFactory(user=None, first_name="Paper", email="paper@example.com")
        entry = _entry(tenant, "LoGnOlOgIn01", member_pk=member.pk)

        _replay(_ledger(tmp_path, entry))

        member.refresh_from_db()
        assert member.first_name == "Gelöscht"
        assert member.email is None

    def test_erases_a_reseller_without_a_login(self, tenant, tmp_path):
        reseller = ResellerFactory(invoice_email="billing@shop.example")
        entry = _entry(tenant, "LoGrEsElLeR1", reseller_pk=reseller.pk)

        _replay(_ledger(tmp_path, entry))

        reseller.refresh_from_db()
        assert reseller.name_for_member_pages == "Gelöscht"
        assert reseller.invoice_email is None

    def test_an_erasure_older_than_the_backup_changes_nothing(self, tenant, tmp_path):
        user = JasminUserFactory(email="early@example.com")
        MemberFactory(user=user)
        log = GDPRService.anonymize_user(user)
        entry = _entry(
            tenant,
            log.pk,
            user_pk=user.pk,
            deleted_at=log.deleted_at.isoformat(),
        )

        output = _replay(_ledger(tmp_path, entry))

        assert DeletionLog.objects.filter(user_pk=user.pk).count() == 1
        assert "1 already erased" in output

    def test_a_subject_newer_than_the_backup_gets_only_its_log_row_back(
        self, tenant, tmp_path
    ):
        entry = _entry(tenant, "LoGnOsUbJeC1", user_pk="NoSuChUsEr12")

        output = _replay(_ledger(tmp_path, entry))

        assert DeletionLog.objects.filter(pk="LoGnOsUbJeC1").exists()
        assert "1 subject not in the restored data" in output

    def test_a_retention_block_skips_the_subject_and_the_rest_continue(
        self, tenant, tmp_path
    ):
        blocked = MemberFactory(user=None, first_name="Blocked")
        # An open share came back with the restore: erasing now would breach
        # the cooperative register obligation.
        CoopShareFactory(member=blocked)
        free = MemberFactory(user=None, first_name="Free")
        ledger = _ledger(
            tmp_path,
            _entry(tenant, "LoGbLoCkEd01", member_pk=blocked.pk),
            _entry(tenant, "LoGfReE00001", member_pk=free.pk),
        )

        output = _replay(ledger)

        blocked.refresh_from_db()
        free.refresh_from_db()
        assert blocked.first_name == "Blocked"
        assert not DeletionLog.objects.filter(pk="LoGbLoCkEd01").exists()
        assert free.first_name == "Gelöscht"
        assert "1 blocked by a retention obligation" in output

    def test_dry_run_reports_and_changes_nothing(self, tenant, tmp_path):
        member = MemberFactory(user=None, first_name="Kept")
        entry = _entry(tenant, "LoGdRyRuN001", member_pk=member.pk)

        output = _replay(_ledger(tmp_path, entry), "--dry-run")

        member.refresh_from_db()
        assert member.first_name == "Kept"
        assert not DeletionLog.objects.filter(pk="LoGdRyRuN001").exists()
        assert "1 would be erased again" in output

    def test_reads_the_ledger_from_stdin(self, tenant, monkeypatch):
        member = MemberFactory(user=None, first_name="Piped")
        line = json.dumps(_entry(tenant, "LoGsTdIn0001", member_pk=member.pk))
        monkeypatch.setattr("sys.stdin", io.StringIO(line + "\n"))

        _replay("-")

        member.refresh_from_db()
        assert member.first_name == "Gelöscht"

    def test_entries_of_a_tenant_the_backup_lacks_are_reported(self, tenant, tmp_path):
        entry = dict(_entry(tenant, "LoGoThErTeN1"), schema="tenant_created_later")

        output = _replay(_ledger(tmp_path, entry))

        assert "1 tenant not in the restored data" in output

    def test_a_member_erased_without_its_login_spares_the_login_again(
        self, tenant, tmp_path
    ):
        """The retention sweep erases an ex-member alone when its login holds
        a staff role, and releases the login. The backup has them linked."""
        admin = JasminUserFactory(email="kept.admin@example.com", roles=[Role.ADMIN])
        member = MemberFactory(user=admin, first_name="Linked")
        entry = _entry(tenant, "LoGkEpTlOgN1", member_pk=member.pk)

        output = _replay(_ledger(tmp_path, entry))

        admin.refresh_from_db()
        member.refresh_from_db()
        assert admin.email == "kept.admin@example.com"
        assert admin.account_status == "active"
        assert admin.roles == [Role.ADMIN]
        assert member.first_name == "Gelöscht"
        assert member.user_id is None
        log = DeletionLog.objects.get(pk="LoGkEpTlOgN1")
        assert (log.user_pk, log.member_pk) == ("", member.pk)
        assert "1 erased again" in output


@pytest.mark.django_db
class TestEntriesWithoutSubjectIds:
    """Rows logged before the log kept subject ids name their user only by
    the email address, which the ledger holds as a SHA-256."""

    def test_erases_the_account_that_existed_at_the_erasure(self, tenant, tmp_path):
        user = JasminUserFactory(
            email="legacy@example.com",
            date_joined=timezone.now() - datetime.timedelta(days=400),
        )
        member = MemberFactory(user=user, first_name="Legacy")
        entry = _entry(
            tenant, "LoGlEgAcY001", email_sha256=email_sha256("Legacy@Example.com")
        )

        _replay(_ledger(tmp_path, entry))

        member.refresh_from_db()
        assert member.first_name == "Gelöscht"

    def test_spares_an_account_signed_up_again_with_the_address(self, tenant, tmp_path):
        """Once an erasure has rewritten the old account's email, the address
        is free and someone can sign up with it again. That later account must
        not be taken for the erased one."""
        erased_at = timezone.now() - datetime.timedelta(days=30)
        newcomer = JasminUserFactory(
            email="again@example.com",
            date_joined=erased_at + datetime.timedelta(days=1),
        )
        member = MemberFactory(user=newcomer, first_name="Newcomer")
        entry = _entry(
            tenant,
            "LoGlEgAcY002",
            deleted_at=erased_at.isoformat(),
            email_sha256=email_sha256("again@example.com"),
        )

        output = _replay(_ledger(tmp_path, entry))

        member.refresh_from_db()
        assert member.first_name == "Newcomer"
        assert "1 subject not in the restored data" in output


class TestReadLedger:
    def test_merges_repeated_entries(self):
        """A later export adds keys to an old row; both lines describe one
        erasure."""
        old = {"schema": "s", "id": "x", "deleted_at": "2026-01-05T10:00:00+00:00"}
        new = dict(old, member_pk="m1")

        entries = read_ledger([json.dumps(old), json.dumps(new)])

        assert len(entries) == 1
        assert entries[0].member_pk == "m1"

    def test_a_line_that_is_not_json_is_an_error(self):
        with pytest.raises(CommandError, match="line 2"):
            read_ledger(['{"schema": "s", "id": "x"}', "not json"])

    def test_a_missing_ledger_file_is_an_error(self, tmp_path):
        with pytest.raises(CommandError, match="No deletion ledger"):
            call_command(
                "replay_gdpr_deletions", "--ledger", str(tmp_path / "missing.jsonl")
            )


@pytest.mark.django_db
class TestLedgerExportFormat:
    """``backup.sh`` writes the ledger with SQL, the replay reads it in
    Python: the two must agree on the line format and the email hash."""

    def test_the_backup_script_query_produces_lines_the_replay_reads(
        self, tenant, tmp_path
    ):
        if not BACKUP_SH.is_file():
            pytest.skip("backups/backup.sh is not in this checkout")
        script = BACKUP_SH.read_text()
        start = script.index("SELECT ((to_jsonb(t)")
        end = script.index("gdpr_deletionlog t;", start) + len("gdpr_deletionlog t")
        # psql fills in the variable ``schema``, quoted; here the test does.
        sql = (
            script[start:end]
            .replace(":'schema'", f"'{tenant.schema_name}'")
            .replace(':"schema"', f'"{tenant.schema_name}"')
        )

        member = MemberFactory(user=None)
        log = DeletionLog.objects.create(
            user_email="  Mixed.Case@Example.com", member_pk=member.pk
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute(sql)
            lines = [row[0] for row in cursor.fetchall()]

        entries = {entry.log_id: entry for entry in read_ledger(lines)}
        exported = entries[log.pk]
        assert exported.schema == tenant.schema_name
        assert exported.member_pk == member.pk
        assert exported.deleted_at == log.deleted_at
        assert (
            exported.email_sha256
            == hashlib.sha256(b"mixed.case@example.com").hexdigest()
        )
        # Nothing that names the person leaves the database.
        assert not any("Mixed.Case" in line for line in lines)
