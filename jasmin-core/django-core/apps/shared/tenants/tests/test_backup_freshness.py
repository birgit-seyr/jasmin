"""Tests for the backup-freshness alert.

Two layers, mirroring ``test_backup_pruning.py``:

  * ``TestStaleBackupKinds`` — pure unit tests against ``stale_backup_kinds``.
    No filesystem and no clock: ``Path`` objects with the right filename shape
    and an explicit ``now``.
  * ``TestAlertOnStaleBackupsTask`` — drives the actual Huey task against
    ``tmp_path`` with ``settings.BACKUP_DIR`` pointed at it, asserting on the
    mail that reaches the admins.

The module runs under a frozen clock: backup filenames encode absolute
timestamps which the task compares against ``timezone.now()``, so the ages the
fixtures set up would drift with the wall clock otherwise.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import time_machine

from apps.shared.tenants.tasks import (
    BACKUP_KINDS,
    _backup_max_age,
    alert_on_stale_backups,
    stale_backup_kinds,
)

# Aware for the traveller (no ambiguity about what a naive instant means),
# naive for the comparisons — the task reads filename timestamps as naive UTC.
_NOW_UTC = datetime.datetime(2026, 6, 3, 12, 0, 0, tzinfo=datetime.UTC)
_NOW = _NOW_UTC.replace(tzinfo=None)
_MAX_AGE = datetime.timedelta(hours=36)


@pytest.fixture(autouse=True)
def _frozen_clock():
    with time_machine.travel(_NOW_UTC, tick=False):
        yield


def _name(kind: str, timestamp: datetime.datetime, *, prefix: str = "jasmin") -> str:
    """A filename in ``backups/backup.sh``'s shape for the given artifact kind.

    The media archive carries the ``_media`` tag and a ``.tar.gz.gpg``
    extension; the DB dump is ``.sql.gz.gpg``.
    """
    if kind == "tar":
        return f"{prefix}_media_{timestamp:%Y%m%d_%H%M%S}.tar.gz.gpg"
    return f"{prefix}_{timestamp:%Y%m%d_%H%M%S}.sql.gz.gpg"


def _ago(hours: float) -> datetime.datetime:
    return _NOW - datetime.timedelta(hours=hours)


class TestStaleBackupKinds:
    def test_both_kinds_fresh_reports_nothing(self):
        paths = [Path(_name("sql", _ago(10))), Path(_name("tar", _ago(10)))]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {}

    def test_stale_dump_is_reported_with_its_newest_timestamp(self):
        stamp = _ago(40)
        paths = [Path(_name("sql", stamp)), Path(_name("tar", _ago(2)))]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {"sql": stamp}

    def test_stale_media_archive_is_not_masked_by_a_fresh_dump(self):
        """The whole point of checking the kinds independently: the DB dump
        landing on time says nothing about the media archive."""
        stamp = _ago(50)
        paths = [Path(_name("sql", _ago(1))), Path(_name("tar", stamp))]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {"tar": stamp}

    def test_absent_kind_reports_none(self):
        paths = [Path(_name("sql", _ago(1)))]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {"tar": None}

    def test_empty_input_reports_every_kind_missing(self):
        expected = dict.fromkeys(BACKUP_KINDS, None)
        assert stale_backup_kinds([], _NOW, _MAX_AGE) == expected

    def test_newest_artifact_of_a_kind_decides(self):
        paths = [
            Path(_name("sql", _ago(24 * 9))),
            Path(_name("sql", _ago(3))),
            Path(_name("tar", _ago(24 * 9))),
            Path(_name("tar", _ago(3))),
        ]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {}

    def test_unparseable_names_never_count_as_a_backup(self):
        """A stray file must not pass for a fresh dump — with only the media
        archive recognisable, the dump reads as absent."""
        paths = [
            Path("README.md"),
            Path("jasmin_backup.sql.gz.gpg"),  # no timestamp
            Path("jasmin_20260603_020000.sql.gz"),  # not encrypted
            Path("jasmin_20261340_020000.sql.gz.gpg"),  # impossible date
            Path(_name("tar", _ago(1))),
        ]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {"sql": None}

    def test_exactly_at_the_threshold_is_still_fresh(self):
        stamp = _NOW - _MAX_AGE
        paths = [Path(_name("sql", stamp)), Path(_name("tar", stamp))]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {}

    def test_a_second_past_the_threshold_is_stale(self):
        stamp = _NOW - _MAX_AGE - datetime.timedelta(seconds=1)
        paths = [Path(_name("sql", stamp)), Path(_name("tar", _ago(1)))]
        assert stale_backup_kinds(paths, _NOW, _MAX_AGE) == {"sql": stamp}


class TestBackupMaxAge:
    def test_reads_the_setting(self, settings):
        settings.BACKUP_MAX_AGE_HOURS = 12
        assert _backup_max_age() == datetime.timedelta(hours=12)

    def test_defaults_to_36_hours_when_unset(self, settings):
        del settings.BACKUP_MAX_AGE_HOURS
        assert _backup_max_age() == datetime.timedelta(hours=36)


class TestAlertOnStaleBackupsTask:
    """Drive the Huey task with ``BACKUP_DIR`` swapped to a ``tmp_path`` so no
    test can see — let alone touch — a real backup directory."""

    def _write(self, tmp_path: Path, kind: str, age_hours: float) -> Path:
        path = tmp_path / _name(kind, _ago(age_hours))
        path.write_bytes(b"fake encrypted backup")
        return path

    def test_both_kinds_fresh_sends_no_mail(self, tmp_path, settings, mailoutbox):
        settings.BACKUP_DIR = str(tmp_path)
        self._write(tmp_path, "sql", 10)
        self._write(tmp_path, "tar", 10)

        result = alert_on_stale_backups.call_local()

        assert mailoutbox == []
        assert result == {
            "kinds_checked": len(BACKUP_KINDS),
            "stale": 0,
            "missing": 0,
            "alerts": 0,
        }

    def test_stale_dump_alerts_naming_the_dump(self, tmp_path, settings, mailoutbox):
        settings.BACKUP_DIR = str(tmp_path)
        self._write(tmp_path, "sql", 40)
        self._write(tmp_path, "tar", 5)

        result = alert_on_stale_backups.call_local()

        assert len(mailoutbox) == 1
        assert "database dump" in mailoutbox[0].subject
        assert "media archive" not in mailoutbox[0].subject
        assert result["stale"] == 1
        assert result["missing"] == 0
        assert result["alerts"] == 1

    def test_stale_media_archive_alerts_while_the_dump_is_fresh(
        self, tmp_path, settings, mailoutbox
    ):
        """The masking case: a DB dump written on time must not hide a media
        archive that stopped being produced."""
        settings.BACKUP_DIR = str(tmp_path)
        self._write(tmp_path, "sql", 3)
        self._write(tmp_path, "tar", 60)

        result = alert_on_stale_backups.call_local()

        assert len(mailoutbox) == 1
        assert "media archive" in mailoutbox[0].subject
        assert "database dump" not in mailoutbox[0].subject
        assert "60.0 h old" in mailoutbox[0].body
        assert result["stale"] == 1
        assert result["missing"] == 0

    def test_absent_media_archive_alerts_as_missing(
        self, tmp_path, settings, mailoutbox
    ):
        settings.BACKUP_DIR = str(tmp_path)
        self._write(tmp_path, "sql", 3)

        result = alert_on_stale_backups.call_local()

        assert len(mailoutbox) == 1
        assert "media archive" in mailoutbox[0].subject
        assert "NO artifact at all" in mailoutbox[0].body
        assert result["missing"] == 1
        assert result["stale"] == 0

    def test_only_unparseable_files_reads_as_both_kinds_missing(
        self, tmp_path, settings, mailoutbox
    ):
        settings.BACKUP_DIR = str(tmp_path)
        (tmp_path / "README.md").write_text("ops notes")

        result = alert_on_stale_backups.call_local()

        assert len(mailoutbox) == 1
        assert "database dump" in mailoutbox[0].subject
        assert "media archive" in mailoutbox[0].subject
        assert result["missing"] == len(BACKUP_KINDS)
        assert result["stale"] == 0

    def test_unreadable_directory_alerts_rather_than_no_op(
        self, tmp_path, settings, mailoutbox
    ):
        """A lost volume mount must not silently disable the alert that is
        supposed to notice silence."""
        settings.BACKUP_DIR = str(tmp_path / "not_mounted")

        result = alert_on_stale_backups.call_local()

        assert len(mailoutbox) == 1
        assert "cannot read the backup directory" in mailoutbox[0].subject
        assert result == {
            "kinds_checked": 0,
            "stale": 0,
            "missing": 0,
            "alerts": 1,
        }

    def test_mail_failure_does_not_fail_the_task(self, tmp_path, settings):
        settings.BACKUP_DIR = str(tmp_path)
        self._write(tmp_path, "sql", 40)
        self._write(tmp_path, "tar", 40)

        with patch(
            "apps.shared.tenants.tasks.mail_admins",
            side_effect=RuntimeError("smtp down"),
        ):
            result = alert_on_stale_backups.call_local()

        # The staleness was still detected and logged; only delivery failed.
        assert result["stale"] == len(BACKUP_KINDS)
        assert result["alerts"] == 0

    def test_threshold_comes_from_the_setting(self, tmp_path, settings, mailoutbox):
        """Ten-hour-old artifacts are fresh under the 36 h default and stale
        under a 6 h window."""
        settings.BACKUP_DIR = str(tmp_path)
        settings.BACKUP_MAX_AGE_HOURS = 6
        self._write(tmp_path, "sql", 10)
        self._write(tmp_path, "tar", 10)

        result = alert_on_stale_backups.call_local()

        assert len(mailoutbox) == 1
        assert result["stale"] == len(BACKUP_KINDS)

    def test_survivors_are_never_touched(self, tmp_path, settings, mailoutbox):
        """The freshness check is read-only — unlike the prune, it must not
        remove anything it looked at."""
        settings.BACKUP_DIR = str(tmp_path)
        dump = self._write(tmp_path, "sql", 40)
        archive = self._write(tmp_path, "tar", 40)

        alert_on_stale_backups.call_local()

        assert dump.exists()
        assert archive.exists()
