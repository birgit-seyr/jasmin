"""The huey container can reach the backup directory the backup container writes.

``backups/backup.sh`` runs as root and closes ``/backups`` to everyone but its
host owner and one group; huey runs as the non-root ``django`` user and prunes
and checks the backups only through that group, which ``docker-compose.yml``
adds to it. The two files have to name the same group and the directory has to
keep the group's access, or ``prune_old_backups`` fails with a PermissionError
and the stale-backup alert can only report the freshness as unknown — neither
of which dev or CI would show, since neither runs the backup service.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[6]
BACKUP_SH = REPO_ROOT / "backups" / "backup.sh"
COMPOSE = REPO_ROOT / "docker-compose.yml"

_GID_DEFAULT_RE = re.compile(r"^\$\{BACKUP_GID:-(\d+)\}$")


@pytest.fixture(scope="module")
def compose_services() -> dict:
    if not COMPOSE.is_file():
        pytest.skip("docker-compose.yml is not in this checkout")
    return yaml.safe_load(COMPOSE.read_text())["services"]


@pytest.fixture(scope="module")
def backup_script() -> str:
    if not BACKUP_SH.is_file():
        pytest.skip("backups/backup.sh is not in this checkout")
    return BACKUP_SH.read_text()


def _default_gid(value: str) -> str:
    match = _GID_DEFAULT_RE.match(value)
    assert match, f"expected ${{BACKUP_GID:-<gid>}}, got {value!r}"
    return match.group(1)


class TestBackupDirectoryGroup:
    def test_huey_joins_the_group_the_backup_service_uses(self, compose_services):
        backup_gid = _default_gid(
            compose_services["backup"]["environment"]["BACKUP_GID"]
        )
        huey_groups = [
            _default_gid(group) for group in compose_services["huey"]["group_add"]
        ]
        assert huey_groups == [backup_gid]

    def test_the_script_default_matches_compose(self, compose_services, backup_script):
        compose_gid = _default_gid(
            compose_services["backup"]["environment"]["BACKUP_GID"]
        )
        assert f'BACKUP_GID="${{BACKUP_GID:-{compose_gid}}}"' in backup_script

    def test_the_directory_is_shared_with_the_group_only(self, backup_script):
        assert 'chgrp "$BACKUP_GID" "$BACKUP_DIR"' in backup_script
        assert 'chmod 2770 "$BACKUP_DIR"' in backup_script
        assert 'chmod 700 "$BACKUP_DIR"' not in backup_script

    def test_huey_mounts_the_directory_writable(self, compose_services):
        # Deleting a backup needs write access to the directory.
        assert "./backups:/backups:rw" in compose_services["huey"]["volumes"]
