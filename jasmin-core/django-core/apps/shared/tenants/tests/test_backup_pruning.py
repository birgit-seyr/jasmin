"""Tests for the GFS backup-pruning logic.

Two layers:

  * ``TestClassifyBackupsForPruning`` — pure unit tests against
    ``classify_backups_for_pruning``. No filesystem; we synthesise
    ``Path`` objects with the correct filename shape and a fixed
    ``now``. Asserts the GFS rule documented in
    docs/gdpr/retention-policy.md:

        - Daily tier (≤ 30 days old): keep every backup
        - Weekly tier (30–365 days old): keep the LATEST backup of
          each ISO week
        - Monthly tier (> 365 days old): keep the LATEST backup of
          each calendar month (forever)

  * ``TestPruneOldBackupsTask`` — drives the actual Huey task body
    against ``tmp_path``. Verifies the filesystem side-effect: only
    the to-be-deleted files actually disappear; survivors stay.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

from apps.shared.tenants.tasks import (
    _parse_timestamp,
    classify_backups_for_pruning,
    prune_old_backups,
)


def _path(name: str) -> Path:
    """Tiny helper to build a fake Path with just a name — the
    classifier never stat()s, only reads ``.name``."""
    return Path(name)


def _backup(ts: datetime.datetime, *, prefix: str = "jasmin") -> Path:
    return _path(f"{prefix}_{ts:%Y%m%d_%H%M%S}.sql.gz.gpg")


_NOW = datetime.datetime(2026, 6, 3, 12, 0, 0)


class TestClassifyBackupsForPruning:
    def test_daily_tier_keeps_everything(self):
        backups = [
            _backup(_NOW - datetime.timedelta(days=d, hours=h))
            for d in range(0, 30)
            for h in (2,)  # one daily backup
        ]
        keep, delete = classify_backups_for_pruning(backups, _NOW)
        assert set(delete) == set()
        assert set(keep) == set(backups)

    def test_weekly_tier_keeps_one_per_iso_week(self):
        # Six daily backups spanning the SAME ISO week, all past the
        # daily cutoff. Only the latest of the six should survive.
        # ISO weeks are Mon–Sun, so we must anchor on a Monday and
        # use ≤ 7 consecutive days; otherwise the span crosses into
        # the next ISO week and the classifier (correctly) keeps two.
        # 2026-04-06 is a Monday (ISO week 15), 58 days before _NOW.
        anchor = datetime.datetime(2026, 4, 6, 2, 0, 0)
        backups = [_backup(anchor + datetime.timedelta(days=i)) for i in range(6)]
        keep, delete = classify_backups_for_pruning(backups, _NOW)
        assert len(keep) == 1
        assert len(delete) == 5
        # The kept one is the newest of the group.
        assert keep[0] == backups[-1]

    def test_monthly_tier_keeps_one_per_calendar_month_forever(self):
        # Three years of daily backups, all older than 365 days. We
        # expect exactly 36 survivors — one per month — and the rest
        # deleted.
        start = _NOW - datetime.timedelta(days=365 * 4)
        backups = [
            _backup(start + datetime.timedelta(days=i))
            for i in range(365 * 3)  # 3 years of dailies
            if (start + datetime.timedelta(days=i))
            < _NOW - datetime.timedelta(days=365)
        ]
        keep, delete = classify_backups_for_pruning(backups, _NOW)

        # Distinct (year, month) pairs in the input (parsed prefix-agnostically
        # so a rename of the backup filename prefix can't skew the offsets):
        months_in_input = {
            (_parse_timestamp(p.name).year, _parse_timestamp(p.name).month)
            for p in backups
        }
        assert len(keep) == len(months_in_input)
        # And every survivor maps to a unique month.
        survivor_months = {
            (_parse_timestamp(p.name).year, _parse_timestamp(p.name).month)
            for p in keep
        }
        assert survivor_months == months_in_input
        # Everything else got deleted.
        assert set(backups) == set(keep) | set(delete)

    def test_unrecognised_filenames_are_never_deleted(self):
        """If the filename doesn't match our pattern we don't know
        when it was taken — so don't delete it. A stray README or
        a backup script we haven't taught the pattern about must
        survive."""
        backups = [
            _path("README.md"),
            _path("some-other-tool.dump"),
            _backup(_NOW - datetime.timedelta(days=400)),  # would be in monthly tier
        ]
        keep, delete = classify_backups_for_pruning(backups, _NOW)
        # The two unrecognised files are in keep.
        assert _path("README.md") in keep
        assert _path("some-other-tool.dump") in keep
        # The monthly-tier dated file is kept too (only one in its month).
        assert len(delete) == 0

    def test_mixed_three_tier_realistic_scenario(self):
        """Simulate a realistic 18-month-old install: 30 daily, 22
        weekly (one per week for ~5 months), 6 monthly. The
        classifier should land on 30 + 22 + 6 = 58 survivors with
        zero deletions when the input matches the GFS shape already."""
        backups = []
        # 30 daily backups (last 30 days).
        for d in range(30):
            backups.append(_backup(_NOW - datetime.timedelta(days=d, hours=2)))
        # 22 weekly backups (Monday of each of the last 22 weeks,
        # offset past the daily cutoff).
        for w in range(5, 27):
            ts = _NOW - datetime.timedelta(weeks=w)
            ts = ts.replace(hour=2)
            backups.append(_backup(ts))
        # 6 monthly backups, one per month going back >1 year.
        for m in range(13, 19):
            ts = _NOW - datetime.timedelta(days=m * 30)
            backups.append(_backup(ts))
        keep, delete = classify_backups_for_pruning(backups, _NOW)
        # No two synthesised inputs collide on the same week/month so
        # nothing should be pruned.
        assert delete == []


class TestPruneOldBackupsTask:
    """Drive the actual Huey task with the filesystem swapped to a
    ``tmp_path``. The contract: files the classifier returns as
    ``delete`` are removed; survivors stay."""

    def _write(self, tmp_path: Path, name: str) -> Path:
        p = tmp_path / name
        p.write_bytes(b"fake encrypted backup")
        return p

    def test_real_filesystem_prune(self, tmp_path):
        # Anchor "now" so the relative ages of the synthesised files
        # don't drift as the wall clock advances past test-write date.
        fake_now = datetime.datetime(2026, 6, 3, 12, 0, 0, tzinfo=datetime.UTC)

        # One file in the daily tier (today), one in the weekly tier
        # (60 days ago), one stale duplicate of the same week to be
        # pruned.
        today = self._write(tmp_path, "jasmin_20260603_020000.sql.gz.gpg")
        weekly = self._write(tmp_path, "jasmin_20260404_020000.sql.gz.gpg")
        # Earlier day of the SAME ISO week as weekly above —
        # 2026-04-04 is a Saturday, week 14; 2026-04-01 (Wed) is also
        # week 14, so the older one should be deleted.
        stale = self._write(tmp_path, "jasmin_20260401_020000.sql.gz.gpg")

        with (
            patch(
                "apps.shared.tenants.tasks._backup_dir",
                return_value=tmp_path,
            ),
            patch(
                "apps.shared.tenants.tasks.timezone.now",
                return_value=fake_now,
            ),
        ):
            result = prune_old_backups.call_local()

        assert today.exists()
        assert weekly.exists()
        assert not stale.exists()
        # Result dict shape for the dev-runner formatter.
        assert result["deleted"] == 1
        assert result["kept"] == 2
        assert result["unrecognised"] == 0

    def test_missing_backup_dir_is_a_noop(self, tmp_path):
        """If the Huey container is misconfigured (no volume mount),
        the task must NOT raise — it logs and returns zeros so the
        scheduler doesn't burn retries on a deployment problem."""
        missing = tmp_path / "does_not_exist"
        with patch("apps.shared.tenants.tasks._backup_dir", return_value=missing):
            result = prune_old_backups.call_local()

        assert result == {"kept": 0, "deleted": 0, "unrecognised": 0}

    def test_unrecognised_files_in_dir_are_left_alone(self, tmp_path):
        readme = self._write(tmp_path, "README.md")
        with patch("apps.shared.tenants.tasks._backup_dir", return_value=tmp_path):
            result = prune_old_backups.call_local()
        assert readme.exists()
        assert result["unrecognised"] == 1
        assert result["deleted"] == 0
