"""Tests for the low-disk-space alert.

Two layers, mirroring ``test_backup_freshness.py``:

  * ``TestDiskSpaceLevel`` / ``TestDiskFreeFloors`` — the pure threshold
    decision and the settings it reads.
  * ``TestAlertOnLowDiskSpaceTask`` — drives the Huey task with
    ``shutil.disk_usage`` replaced, so any free-space figure can be staged
    without a real disk, and asserts on the mail that reaches the admins.

A mail holds back the next one of its level for a day through a mark in the
cache, so the module runs under a frozen clock that the window tests move
forward, and gives every test an in-memory cache of its own. The configured
cache is Redis wherever ``REDIS_URL`` is set, as in the dev backend container
``make pytest`` runs in: Redis expires a mark on its own clock, which the frozen
clock can't move, and keeps it after the test, where a later run measuring the
same ``tmp_path`` would find it.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections import namedtuple
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import pytest
import time_machine

from apps.shared.tenants.management.commands.run_periodic_tasks_now import (
    TASK_REGISTRY,
)
from apps.shared.tenants.tasks import (
    _disk_free_floors,
    alert_on_low_disk_space,
    disk_space_level,
)

# A Monday, clear of any year boundary.
_NOW = datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)
_GIB = 2**30

# ``shutil.disk_usage``'s result: ``free`` is what a non-root writer can use,
# so ``used + free`` falls short of ``total`` by the blocks reserved for root.
_Usage = namedtuple("_Usage", "total used free")


@pytest.fixture(autouse=True)
def clock():
    with time_machine.travel(_NOW, tick=False) as traveller:
        yield traveller


@pytest.fixture(autouse=True)
def private_cache(settings):
    """A ``LocMemCache`` for the test alone; its entries expire by ``time.time()``,
    which the frozen clock moves. Instances of one location share their entries,
    hence the unique one."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"test-disk-space-alert-{uuid.uuid4().hex}",
        }
    }


@pytest.fixture
def watched_dirs(tmp_path, settings) -> tuple[Path, Path]:
    """``(backups, media)``: the two directories the task measures."""
    backups = tmp_path / "backups"
    media = tmp_path / "media"
    settings.BACKUP_DIR = str(backups)
    settings.MEDIA_ROOT = media
    return backups, media


@pytest.fixture
def task_log(caplog):
    """The messages of the ``tasks`` logger. It doesn't propagate to the root
    logger caplog listens on, so caplog's handler is attached to it directly."""
    tasks_logger = logging.getLogger("tasks")
    tasks_logger.addHandler(caplog.handler)
    yield lambda: [record.getMessage() for record in caplog.records]
    tasks_logger.removeHandler(caplog.handler)


def _usage(free_percent: float, total_gib: int = 100) -> _Usage:
    total = total_gib * _GIB
    free = int(total * free_percent / 100)
    return _Usage(total=total, used=total - free, free=free)


@contextmanager
def _disks(by_dir: dict[Path, _Usage | OSError]) -> Iterator[None]:
    """Stage what ``shutil.disk_usage`` reports for each directory."""

    def disk_usage(path):
        answer = by_dir[Path(path)]
        if isinstance(answer, OSError):
            raise answer
        return answer

    with patch("apps.shared.tenants.tasks.shutil.disk_usage", side_effect=disk_usage):
        yield


class TestDiskSpaceLevel:
    @pytest.mark.parametrize(
        ("free_percent", "expected"),
        [
            (55.0, None),
            (20.0, None),
            (19.9, "warning"),
            (10.0, "warning"),
            (9.9, "critical"),
            (0.0, "critical"),
        ],
    )
    def test_level_by_free_space(self, free_percent, expected):
        assert disk_space_level(free_percent, warning=20, critical=10) == expected


class TestDiskFreeFloors:
    def test_reads_the_settings(self, settings):
        settings.DISK_FREE_WARNING_PERCENT = 30
        settings.DISK_FREE_CRITICAL_PERCENT = 15
        assert _disk_free_floors() == (30.0, 15.0)

    def test_defaults_to_20_and_10_percent_when_unset(self, settings):
        del settings.DISK_FREE_WARNING_PERCENT
        del settings.DISK_FREE_CRITICAL_PERCENT
        assert _disk_free_floors() == (20.0, 10.0)


class TestAlertOnLowDiskSpaceTask:
    def test_enough_room_sends_no_mail(self, watched_dirs, mailoutbox):
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(45)}):
            result = alert_on_low_disk_space.call_local()

        assert mailoutbox == []
        assert result == {
            "dirs_checked": 2,
            "unreadable": 0,
            "warning": 0,
            "critical": 0,
            "alerts": 0,
        }

    def test_under_the_warning_floor_mails_a_warning(self, watched_dirs, mailoutbox):
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(15)}):
            result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 1
        assert "(warning)" in mailoutbox[0].subject
        assert f"15.0% free on {media}" in mailoutbox[0].subject
        assert f"{media}: 15.0% free, 15.0 of 100.0 GiB (warning)" in mailoutbox[0].body
        assert str(backups) not in mailoutbox[0].body
        assert result == {
            "dirs_checked": 2,
            "unreadable": 0,
            "warning": 1,
            "critical": 0,
            "alerts": 1,
        }

    def test_under_the_critical_floor_mails_a_critical_alert(
        self, watched_dirs, mailoutbox
    ):
        backups, media = watched_dirs
        with _disks({backups: _usage(5), media: _usage(60)}):
            result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 1
        assert "(critical)" in mailoutbox[0].subject
        assert f"5.0% free on {backups}" in mailoutbox[0].subject
        assert result["critical"] == 1
        assert result["warning"] == 0
        assert result["alerts"] == 1

    def test_free_space_decides_not_used_space(self, watched_dirs, mailoutbox):
        """75 % used reads as room to spare, but with 10 % of the disk reserved
        for root only 15 % is left to Postgres and Redis: a warning."""
        backups, media = watched_dirs
        reserved_for_root = _Usage(total=100 * _GIB, used=75 * _GIB, free=15 * _GIB)
        with _disks({backups: _usage(60), media: reserved_for_root}):
            result = alert_on_low_disk_space.call_local()

        assert result["warning"] == 1
        assert len(mailoutbox) == 1

    def test_one_mail_covers_every_low_directory(self, watched_dirs, mailoutbox):
        """On a single-disk host both directories report the same filesystem
        and cross a floor in the same run: one mail names both."""
        backups, media = watched_dirs
        with _disks({backups: _usage(8), media: _usage(8)}):
            result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 1
        assert f"{backups}: 8.0% free" in mailoutbox[0].body
        assert f"{media}: 8.0% free" in mailoutbox[0].body
        assert result["critical"] == 2
        assert result["alerts"] == 1

    def test_no_second_mail_within_a_day(self, watched_dirs, mailoutbox, clock):
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(15)}):
            alert_on_low_disk_space.call_local()
            for _ in range(23):
                clock.shift(datetime.timedelta(hours=1))
                result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 1
        # Still low, and still counted, only not mailed again.
        assert result["warning"] == 1
        assert result["alerts"] == 0

    def test_mails_again_a_day_later(self, watched_dirs, mailoutbox, clock):
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(15)}):
            alert_on_low_disk_space.call_local()
            clock.shift(datetime.timedelta(days=1, minutes=1))
            result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 2
        assert result["alerts"] == 1

    def test_turning_critical_mails_within_the_day(
        self, watched_dirs, mailoutbox, clock
    ):
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(15)}):
            alert_on_low_disk_space.call_local()
        clock.shift(datetime.timedelta(hours=1))
        with _disks({backups: _usage(60), media: _usage(6)}):
            result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 2
        assert "(warning)" in mailoutbox[0].subject
        assert "(critical)" in mailoutbox[1].subject
        assert result["alerts"] == 1

    def test_a_second_directory_turning_low_mails_within_the_day(
        self, watched_dirs, mailoutbox, clock
    ):
        """Two filesystems: the one that fills up second is not held back by
        the mail about the first."""
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(15)}):
            alert_on_low_disk_space.call_local()
        clock.shift(datetime.timedelta(hours=1))
        with _disks({backups: _usage(12), media: _usage(15)}):
            result = alert_on_low_disk_space.call_local()

        assert len(mailoutbox) == 2
        assert str(backups) in mailoutbox[1].subject
        # The second mail still lists the first directory.
        assert f"{media}: 15.0% free" in mailoutbox[1].body
        assert result["warning"] == 2
        assert result["alerts"] == 1

    def test_a_failed_mail_is_tried_again_the_next_hour(
        self, watched_dirs, mailoutbox, clock, task_log
    ):
        backups, media = watched_dirs
        with _disks({backups: _usage(60), media: _usage(5)}):
            with patch(
                "apps.shared.tenants.tasks.mail_admins",
                side_effect=RuntimeError("smtp down"),
            ):
                failed = alert_on_low_disk_space.call_local()
            clock.shift(datetime.timedelta(hours=1))
            retried = alert_on_low_disk_space.call_local()

        assert failed["alerts"] == 0
        assert "disk.space.alert_failed" in task_log()
        assert retried["alerts"] == 1
        assert len(mailoutbox) == 1

    def test_an_unreadable_directory_is_logged_and_the_other_still_checked(
        self, watched_dirs, mailoutbox, task_log
    ):
        backups, media = watched_dirs
        missing = FileNotFoundError(2, "No such file or directory", str(backups))
        with _disks({backups: missing, media: _usage(5)}):
            result = alert_on_low_disk_space.call_local()

        assert result == {
            "dirs_checked": 1,
            "unreadable": 1,
            "warning": 0,
            "critical": 1,
            "alerts": 1,
        }
        assert any(
            line.startswith(f"disk.space.unreadable dir={backups} ")
            for line in task_log()
        )
        assert len(mailoutbox) == 1
        assert str(backups) not in mailoutbox[0].body

    def test_no_measurable_directory_logs_without_crashing(
        self, watched_dirs, mailoutbox, task_log
    ):
        backups, media = watched_dirs
        with _disks(
            {
                backups: PermissionError(13, "Permission denied"),
                media: OSError(5, "I/O"),
            }
        ):
            result = alert_on_low_disk_space.call_local()

        assert result == {
            "dirs_checked": 0,
            "unreadable": 2,
            "warning": 0,
            "critical": 0,
            "alerts": 0,
        }
        assert mailoutbox == []
        unreadable = [
            line for line in task_log() if line.startswith("disk.space.unreadable")
        ]
        assert len(unreadable) == 2

    def test_floors_come_from_the_settings(self, watched_dirs, settings, mailoutbox):
        """40 % free is enough room under the 20 % default and a warning under a
        50 % floor."""
        backups, media = watched_dirs
        settings.DISK_FREE_WARNING_PERCENT = 50
        with _disks({backups: _usage(60), media: _usage(40)}):
            result = alert_on_low_disk_space.call_local()

        assert result["warning"] == 1
        assert len(mailoutbox) == 1
        assert "warning under 50% free" in mailoutbox[0].body

    def test_a_failing_cache_lets_the_mail_through(self, watched_dirs, mailoutbox):
        backups, media = watched_dirs
        with (
            _disks({backups: _usage(60), media: _usage(5)}),
            patch("apps.shared.tenants.tasks.cache") as broken_cache,
        ):
            broken_cache.get.side_effect = ConnectionError("redis refuses")
            broken_cache.set.side_effect = ConnectionError("redis refuses")
            result = alert_on_low_disk_space.call_local()

        assert result["alerts"] == 1
        assert len(mailoutbox) == 1


class TestRegistration:
    def test_the_dev_runner_lists_it(self):
        assert "alert_on_low_disk_space" in TASK_REGISTRY["apps.shared.tenants.tasks"]

    def test_runs_every_hour(self):
        task = alert_on_low_disk_space.s()
        midnight = datetime.datetime(2026, 6, 1)
        runs = [
            minute
            for minute in range(24 * 60)
            if task.validate_datetime(midnight + datetime.timedelta(minutes=minute))
        ]
        assert len(runs) == 24
        assert {later - earlier for earlier, later in pairwise(runs)} == {60}
