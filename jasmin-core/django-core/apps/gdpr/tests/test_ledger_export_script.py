"""``backups/backup.sh`` only ever adds to the GDPR deletion ledger.

The ledger keeps an erasure after a restore has taken its log row out of the
database, so an export may add lines but must never leave fewer. The nightly
run and the container start call ``export_gdpr_ledger || true``, which turns
``set -e`` off inside the function: every step has to check its own status, or
a merge a full disk cut short replaces the ledger, and its off-host copy with
it. These tests run the script's ledger section under ``sh`` in that state,
with ``psql``, the encryption and the off-host push stubbed, and ``sort`` or
``mv`` failing the way they fail on a full disk.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKUP_SH = Path(__file__).resolve().parents[5] / "backups" / "backup.sh"
LEDGER_NAME = "gdpr-deletion-ledger.jsonl"

SEEDED = sorted(f'{{"id": "erasure-{n:04d}", "schema": "t1"}}' for n in range(40))
NEW_ENTRY = '{"id": "new-0001", "schema": "t2"}'

# Sets -e like the script and calls the export the way its callers do, so the
# function body runs with -e off.
_HARNESS = """set -eu
BACKUP_DIR="$1"
DB_HOST=postgres DB_PORT=5432 DB_USER=backup DB_NAME=jasmin
encrypt_gpg() { cat > "$1"; }
push_offsite() { cp "$1" "${BACKUP_DIR}/pushed.gpg"; }
@LEDGER_SECTION@
status=0
export_gdpr_ledger || status=$?
echo "export returned ${status}"
exit "$status"
"""

# psql reads its SQL from stdin, kept in <schema>.sql (list.sql for the tenant
# list), and gets the schema as the variable ``schema``. It prints the tenant
# list, then per tenant what <schema>.out holds, exiting with the status in
# <schema>.status (0 when there is none).
_PSQL = """bin=$(dirname "$0")
schema=""
for arg in "$@"; do
    case "$arg" in
        schema=*) schema="${arg#schema=}" ;;
    esac
done
cat > "$bin/${schema:-list}.sql"
if [ -z "$schema" ]; then
    printf 't1\\nt2\\n'
    exit 0
fi
cat "$bin/$schema.out"
exit "$(cat "$bin/$schema.status" 2>/dev/null || echo 0)"
"""


@dataclass
class Backups:
    dir: Path
    bin: Path

    @property
    def ledger(self) -> Path:
        return self.dir / LEDGER_NAME

    @property
    def encrypted(self) -> Path:
        return self.dir / f"{LEDGER_NAME}.gpg"

    @property
    def pushed(self) -> Path:
        return self.dir / "pushed.gpg"

    def tenant_rows(self, schema: str, text: str, status: int = 0) -> None:
        (self.bin / f"{schema}.out").write_text(text)
        (self.bin / f"{schema}.status").write_text(f"{status}\n")

    def stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def leftovers(self) -> list[str]:
        return [
            p.name for p in self.dir.iterdir() if p.suffix in {".rows", ".part", ".new"}
        ]


@pytest.fixture
def ledger_section() -> str:
    if not BACKUP_SH.is_file():
        pytest.skip("backups/backup.sh is not in this checkout")
    script = BACKUP_SH.read_text()
    return script[
        script.index("# ── GDPR deletion ledger") : script.index("# ── Media backup")
    ]


@pytest.fixture
def backups(tmp_path: Path) -> Backups:
    backups = Backups(dir=tmp_path / "backups", bin=tmp_path / "bin")
    backups.dir.mkdir()
    backups.bin.mkdir()
    seeded = "".join(f"{line}\n" for line in SEEDED)
    backups.ledger.write_text(seeded)
    backups.encrypted.write_text(seeded)
    backups.stub("psql", _PSQL)
    backups.tenant_rows("t1", f"{SEEDED[0]}\n")
    backups.tenant_rows("t2", f"{NEW_ENTRY}\n")
    return backups


def run_export(
    backups: Backups, ledger_section: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{backups.bin}{os.pathsep}{os.environ['PATH']}",
        "LC_ALL": "C",
    }
    return subprocess.run(
        [
            "sh",
            "-c",
            _HARNESS.replace("@LEDGER_SECTION@", ledger_section),
            "sh",
            str(backups.dir),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def assert_ledger_untouched(backups: Backups) -> None:
    seeded = "".join(f"{line}\n" for line in SEEDED)
    assert backups.ledger.read_text() == seeded
    assert backups.encrypted.read_text() == seeded
    assert not backups.pushed.exists()
    assert backups.leftovers() == []


def _failing_sort(status: int) -> str:
    """A sort that prints the first 150 bytes of its output, cutting a line in
    two, and exits with ``status``; after one such run it works again."""
    real_sort = shutil.which("sort")
    assert real_sort, "the tests need a sort on PATH"
    return (
        'if [ ! -f "$(dirname "$0")/sort.failed" ]; then\n'
        '    touch "$(dirname "$0")/sort.failed"\n'
        f'    "{real_sort}" "$@" | head -c 150\n'
        f"    exit {status}\n"
        "fi\n"
        f'exec "{real_sort}" "$@"\n'
    )


class TestLedgerExport:
    def test_a_new_entry_is_merged_encrypted_and_pushed(self, backups, ledger_section):
        result = run_export(backups, ledger_section)

        assert result.returncode == 0, result.stderr
        assert backups.ledger.read_text().splitlines() == sorted([*SEEDED, NEW_ENTRY])
        assert backups.encrypted.read_text() == backups.ledger.read_text()
        assert backups.pushed.read_text() == backups.ledger.read_text()
        assert backups.leftovers() == []

    def test_each_table_is_locked_and_checked_before_it_is_read(
        self, backups, ledger_section
    ):
        # The app writes these tables and names the schemas: a schema reaches
        # psql as a variable it quotes, and a view put under a table's name
        # would run the app's code.
        result = run_export(backups, ledger_section)

        assert result.returncode == 0, result.stderr
        tenant_sql = (backups.bin / "t1.sql").read_text()
        assert "t1" not in tenant_sql
        assert (
            tenant_sql.index('LOCK TABLE :"schema".gdpr_deletionlog')
            < tenant_sql.index("relkind = 'r'")
            < tenant_sql.index('FROM :"schema".gdpr_deletionlog t')
        )
        listing_sql = (backups.bin / "list.sql").read_text()
        assert (
            listing_sql.index("LOCK TABLE public.tenants_tenant")
            < listing_sql.index("relkind = 'r'")
            < listing_sql.index("SELECT schema_name FROM public.tenants_tenant")
        )

    def test_an_export_with_nothing_new_writes_nothing(self, backups, ledger_section):
        backups.tenant_rows("t2", f"{SEEDED[1]}\n")

        result = run_export(backups, ledger_section)

        assert result.returncode == 0, result.stderr
        assert_ledger_untouched(backups)

    def test_a_merge_the_disk_cut_short_changes_nothing(self, backups, ledger_section):
        backups.stub("sort", _failing_sort(status=2))

        result = run_export(backups, ledger_section)

        assert result.returncode == 1
        assert "cannot write the merged ledger" in result.stderr
        assert_ledger_untouched(backups)

    def test_a_cut_merge_that_sort_reports_as_written_changes_nothing(
        self, backups, ledger_section
    ):
        backups.stub("sort", _failing_sort(status=0))

        result = run_export(backups, ledger_section)

        assert result.returncode == 1
        assert "cannot write the merged ledger" in result.stderr
        assert_ledger_untouched(backups)

    def test_a_tenant_whose_read_fails_adds_nothing(self, backups, ledger_section):
        # psql printed a whole line and part of the next before it failed.
        backups.tenant_rows(
            "t1", '{"id": "cut-0001", "schema": "t1"}\n{"id": "cut-0', status=1
        )

        result = run_export(backups, ledger_section)

        assert result.returncode == 0, result.stderr
        assert "could not read t1.gdpr_deletionlog" in result.stderr
        assert backups.ledger.read_text().splitlines() == sorted([*SEEDED, NEW_ENTRY])
        assert backups.leftovers() == []

    def test_a_rows_file_it_cannot_write_fails_the_export_not_the_script(
        self, backups, ledger_section
    ):
        (backups.dir / f"{LEDGER_NAME}.rows").mkdir()

        result = run_export(backups, ledger_section)

        assert result.returncode == 1
        assert "export returned 1" in result.stdout
        assert backups.ledger.read_text().splitlines() == SEEDED
        assert not backups.pushed.exists()

    def test_a_failed_replace_keeps_the_ledger(self, backups, ledger_section):
        backups.stub("mv", 'echo "mv: stub failure" >&2\nexit 1\n')

        result = run_export(backups, ledger_section)

        assert result.returncode == 1
        assert "cannot replace" in result.stderr
        assert "ledger updated" not in result.stdout
        assert_ledger_untouched(backups)
