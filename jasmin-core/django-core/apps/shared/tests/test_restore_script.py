"""``backups/restore.sh`` never replays a dump over the live database.

The dumps carry ``--clean`` DROP statements without CASCADE, which fail on
whatever was added since the dump was taken: a table in a tenant schema, a
foreign key into a dumped table, a new tenant's schema. So the script restores
into a new database, ``<db>_restore``, drops it again when the restore fails,
and only on an explicit confirmation swaps the names, both renames in one
transaction, keeping the replaced database. It refuses the swap while client
sessions are connected to the live database or keep connecting to it, and
refreshes the GDPR deletion ledger once more right before it.

These tests run a copy of the script under ``sh`` with psql, gpg and sleep
stubbed on the PATH and backup.sh replaced by a stub. The psql stub records
every call and plays the server's side on a list of database names and a list
of sessions. The restore against a real Postgres, over a migrated copy too, is
what ``scripts/restore_drill.sh`` runs.
"""

from __future__ import annotations

import gzip
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
RESTORE_SH = REPO_ROOT / "backups" / "restore.sh"
# Where the backup image installs backup.sh, which restore.sh runs for the
# ledger refreshes. The copy under test runs the stub instead.
BACKUP_SH_IN_IMAGE = "/usr/local/bin/backup.sh"

# Writes each call to $PSQL_STUB/calls/NNN — the database, the file, the -v
# variables, then the SQL from stdin — and answers for the server from
# $PSQL_STUB/databases (one name per line), $PSQL_STUB/sessions (one
# "<backend_type>|<row>" line per session on the live database), the flag
# files replay_fails and sessions_come_back, and session_pattern: with it the
# sessions belong to an app that connects only now and then, and the n-th
# session check sees them where the pattern's n-th character is "+" (the
# last character repeats).
_PSQL = r"""#!/bin/sh
stub="$PSQL_STUB"
databases="$stub/databases"
sessions="$stub/sessions"
db="" file="" vars="" prev=""
for arg; do
    case "$prev" in
        -d) db="$arg" ;;
        -f) file="$arg" ;;
        -v) vars="$vars $arg" ;;
    esac
    prev="$arg"
done
var() {
    for pair in $vars; do
        case "$pair" in "$1="*) echo "${pair#*=}"; return ;; esac
    done
}
has() { grep -qx "$1" "$databases"; }
without() { grep -vx "$1" "$databases" > "$databases.new"; mv "$databases.new" "$databases"; }
seen() {
    [ -f "$stub/session_pattern" ] || return 0
    checks=$(( $(cat "$stub/checks" 2>/dev/null || echo 0) + 1 ))
    echo "$checks" > "$stub/checks"
    pattern=$(cat "$stub/session_pattern")
    mark=$(printf '%s' "$pattern" | cut -c"$checks")
    [ -n "$mark" ] || mark=$(printf '%s' "$pattern" | tail -c 1)
    [ "$mark" = "+" ]
}

sql=""
if [ -z "$file" ]; then
    sql=$(cat)
fi
count=$(ls "$stub/calls" | wc -l | tr -d ' ')
{
    echo "db=$db"
    echo "file=$file"
    echo "args=$*"
    printf '%s\n' "$sql"
} > "$stub/calls/$(printf '%03d' $((count + 1)))"

if [ -n "$file" ]; then
    if [ -f "$stub/replay_fails" ]; then
        echo "psql:$file:42: ERROR:  cannot drop constraint" >&2
        exit 3
    fi
    exit 0
fi
case "$sql" in
    *"ALTER DATABASE"*)
        # As in Postgres: the rename ends autovacuum workers itself, and any
        # other session refuses it. An app between two requests holds none.
        if [ -f "$sessions" ] && [ ! -f "$stub/session_pattern" ] \
                && grep -qv "^autovacuum worker|" "$sessions"; then
            echo "ERROR:  database \"$(var live)\" is being accessed by other users" >&2
            exit 3
        fi
        rm -f "$sessions"
        if has "$(var live)"; then
            without "$(var live)"
            echo "$(var replaced)" >> "$databases"
        fi
        without "$(var restore)"
        echo "$(var live)" >> "$databases"
        ;;
    *"CREATE DATABASE"*) echo "$(var restore)" >> "$databases" ;;
    *"DROP DATABASE"*) without "$(var name)" ;;
    *"pg_terminate_backend"*)
        if [ -f "$sessions" ] && [ ! -f "$stub/sessions_come_back" ]; then
            case "$sql" in
                *"backend_type = 'client backend'"*)
                    grep -v "^client backend|" "$sessions" > "$sessions.new" ;;
                *) : > "$sessions.new" ;;
            esac
            mv "$sessions.new" "$sessions"
        fi
        ;;
    *"FROM pg_stat_activity"*)
        if [ -f "$sessions" ] && seen; then
            case "$sql" in
                *"backend_type = 'client backend'"*)
                    grep "^client backend|" "$sessions" | cut -d'|' -f2- ;;
                *) cut -d'|' -f2- "$sessions" ;;
            esac
        fi
        ;;
    *"pg_db_role_setting"*) ;;
    *"pg_size_pretty"*) echo "8 MB" ;;
    *"pg_temp.row_count"*) printf ' schema | tables\n public |      4\n' ;;
    *"FROM pg_database WHERE datname"*)
        if has "$(var name)"; then echo 1; else echo 0; fi
        ;;
esac
exit 0
"""

# Records each run as a call ("backup.sh <args>" in place of the SQL) and
# fails the n-th one when $PSQL_STUB/refresh_fails_<n> exists.
_BACKUP_SH = r"""#!/bin/sh
stub="$PSQL_STUB"
count=$(ls "$stub/calls" | wc -l | tr -d ' ')
printf 'db=\nfile=\nargs=%s\nbackup.sh %s\n' "$*" "$*" \
    > "$stub/calls/$(printf '%03d' $((count + 1)))"
runs=$(( $(cat "$stub/refreshes" 2>/dev/null || echo 0) + 1 ))
echo "$runs" > "$stub/refreshes"
if [ -f "$stub/refresh_fails_$runs" ]; then
    echo "ERROR: GDPR ledger: cannot list tenant schemas" >&2
    exit 1
fi
exit 0
"""

# Decrypts by copying the input file to --output.
_GPG = """#!/bin/sh
out="" prev="" last=""
for arg; do
    if [ "$prev" = "--output" ]; then
        out="$arg"
    fi
    prev="$arg"
    last="$arg"
done
cp "$last" "$out"
"""

_SLEEP = "#!/bin/sh\nexit 0\n"

# How pg_dump ends a plain dump: its completion trailer, then the \unrestrict
# line pg_dump 15.14 and later add.
DUMP_END = b"\n--\n-- PostgreSQL database dump complete\n--\n\n\\unrestrict key\n\n"

LIVE = "jasmin"
RESTORE = "jasmin_restore"
SESSION = "4242 | jasmin | gunicorn | 172.18.0.5 | idle"
AUTOVACUUM = "266 |  | - | local socket | active"


@dataclass(frozen=True)
class Call:
    database: str
    file: str
    args: str
    sql: str

    @property
    def is_ledger_refresh(self) -> bool:
        return self.sql.startswith("backup.sh ledger")

    @property
    def is_session_check(self) -> bool:
        return "FROM pg_stat_activity" in self.sql and not self.is_termination

    @property
    def is_termination(self) -> bool:
        return "pg_terminate_backend" in self.sql

    @property
    def is_swap(self) -> bool:
        return "ALTER DATABASE" in self.sql


@dataclass
class Restore:
    dir: Path

    @property
    def stub(self) -> Path:
        return self.dir / "stub"

    @property
    def script(self) -> Path:
        return self.dir / "restore.sh"

    @property
    def dump(self) -> Path:
        return self.dir / "backups" / "jasmin_20261012_020000.sql.gz.gpg"

    def databases(self) -> set[str]:
        return set((self.stub / "databases").read_text().split())

    def set_databases(self, *names: str) -> None:
        (self.stub / "databases").write_text("".join(f"{name}\n" for name in names))

    def connect_session(
        self, row: str = SESSION, backend_type: str = "client backend"
    ) -> None:
        with (self.stub / "sessions").open("a") as sessions:
            sessions.write(f"{backend_type}|{row}\n")

    def let_sessions_come_back(self) -> None:
        (self.stub / "sessions_come_back").touch()

    def connect_now_and_then(self, pattern: str) -> None:
        (self.stub / "session_pattern").write_text(pattern)

    def fail_the_replay(self) -> None:
        (self.stub / "replay_fails").touch()

    def fail_ledger_refresh(self, run: int) -> None:
        (self.stub / f"refresh_fails_{run}").touch()

    def calls(self) -> list[Call]:
        calls = []
        for path in sorted((self.stub / "calls").iterdir()):
            database, file, args, sql = path.read_text().split("\n", 3)
            calls.append(
                Call(
                    database=database.removeprefix("db="),
                    file=file.removeprefix("file="),
                    args=args.removeprefix("args="),
                    sql=sql,
                )
            )
        return calls

    def replays(self) -> list[Call]:
        return [call for call in self.calls() if call.file]

    def renames(self) -> list[Call]:
        return [call for call in self.calls() if call.is_swap]

    def ledger_refreshes(self) -> list[int]:
        """The positions of the ledger refreshes among all calls."""
        return [i for i, call in enumerate(self.calls()) if call.is_ledger_refresh]

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        inherited = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("POSTGRES_")
            and key not in {"CONFIRM_SWAP", "TERMINATE_SESSIONS"}
        }
        return subprocess.run(
            ["sh", str(self.script), str(self.dump)],
            env={
                **inherited,
                "PATH": f"{self.dir / 'bin'}{os.pathsep}{os.environ['PATH']}",
                "PSQL_STUB": str(self.stub),
                "POSTGRES_HOST": "postgres",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": LIVE,
                "POSTGRES_USER": "jasmin",
                "POSTGRES_PASSWORD": "secret",
                "BACKUP_ENCRYPTION_KEY": "key",
                "ALLOW_MISSING_GDPR_LEDGER": "1",
                **env,
            },
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.fixture
def restore(tmp_path: Path) -> Restore:
    if not RESTORE_SH.is_file():
        pytest.skip("backups/restore.sh is not in this checkout")
    restore = Restore(dir=tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = (
        ("psql", _PSQL),
        ("gpg", _GPG),
        ("sleep", _SLEEP),
        ("backup.sh", _BACKUP_SH),
    )
    for name, body in stubs:
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    script = RESTORE_SH.read_text()
    assert BACKUP_SH_IN_IMAGE in script
    restore.script.write_text(
        script.replace(BACKUP_SH_IN_IMAGE, str(bin_dir / "backup.sh"))
    )
    (restore.stub / "calls").mkdir(parents=True)
    restore.set_databases("postgres", "glitchtip", LIVE)
    restore.dump.parent.mkdir()
    restore.dump.write_bytes(gzip.compress(b"SELECT 1;\n" + DUMP_END))
    return restore


class TestRestoreIntoANewDatabase:
    def test_the_dump_goes_into_a_new_database_and_the_names_swap(self, restore):
        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert [call.database for call in restore.replays()] == [RESTORE]
        [swap] = restore.renames()
        assert swap.sql.index("BEGIN;") < swap.sql.index("ALTER DATABASE")
        assert swap.sql.count("ALTER DATABASE") == 2
        assert swap.sql.rstrip().endswith("COMMIT;")
        databases = restore.databases()
        [replaced] = [name for name in databases if name.startswith(f"{LIVE}_pre_")]
        assert replaced.startswith(f"{LIVE}_pre_restore_")
        assert databases == {"postgres", "glitchtip", LIVE, replaced}
        assert f"dropdb -U jasmin {replaced}" in result.stdout

    def test_the_replay_runs_without_one_transaction_around_it(self, restore):
        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        [replay] = restore.replays()
        assert "--single-transaction" not in replay.args
        assert "ON_ERROR_STOP=1" in replay.args

    def test_the_new_database_is_created_before_the_replay(self, restore):
        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        calls = restore.calls()
        create = next(i for i, c in enumerate(calls) if "CREATE DATABASE" in c.sql)
        replay = next(i for i, c in enumerate(calls) if c.file)
        assert create < replay
        assert "TEMPLATE template0" in calls[create].sql

    def test_a_leftover_copy_is_dropped_first(self, restore):
        restore.set_databases("postgres", LIVE, RESTORE)

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert f"Dropping {RESTORE}, left over" in result.stdout
        calls = restore.calls()
        drop = next(i for i, c in enumerate(calls) if "DROP DATABASE" in c.sql)
        create = next(i for i, c in enumerate(calls) if "CREATE DATABASE" in c.sql)
        assert drop < create

    def test_without_a_live_database_the_copy_is_only_renamed(self, restore):
        restore.set_databases("postgres")

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert len(restore.renames()) == 1
        assert restore.databases() == {"postgres", LIVE}
        assert f"Renaming {RESTORE} to {LIVE}" in result.stdout
        assert len(restore.ledger_refreshes()) == 1

    def test_no_temp_file_is_left_next_to_the_dump(self, restore):
        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert sorted(p.name for p in restore.dump.parent.iterdir()) == [
            restore.dump.name
        ]


class TestTheLiveDatabaseStaysAsItWas:
    def test_a_dump_cut_short_is_refused_before_anything_is_created(self, restore):
        restore.dump.write_bytes(gzip.compress(b"--\n-- PostgreSQL database dump\n"))

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 1
        assert not any("CREATE DATABASE" in call.sql for call in restore.calls())
        assert restore.replays() == []
        assert restore.renames() == []
        assert restore.databases() == {"postgres", "glitchtip", LIVE}
        assert "does not end like a complete pg_dump" in result.stderr
        assert sorted(p.name for p in restore.dump.parent.iterdir()) == [
            restore.dump.name
        ]

    def test_a_failed_restore_drops_the_new_database(self, restore):
        restore.fail_the_replay()

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode != 0
        assert [call.database for call in restore.replays()] == [RESTORE]
        assert restore.renames() == []
        assert restore.databases() == {"postgres", "glitchtip", LIVE}
        assert f"{LIVE} is unchanged" in result.stderr

    def test_without_a_confirmation_nothing_is_renamed(self, restore):
        result = restore.run()

        assert result.returncode == 0, result.stderr
        assert [call.database for call in restore.replays()] == [RESTORE]
        assert restore.renames() == []
        assert restore.databases() == {"postgres", "glitchtip", LIVE, RESTORE}
        assert f"Not swapped: {LIVE} is unchanged" in result.stdout


class TestSessionsOnTheLiveDatabase:
    def test_a_connected_session_blocks_the_swap(self, restore):
        restore.connect_session()

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 1
        assert restore.renames() == []
        assert not any(call.is_termination for call in restore.calls())
        assert SESSION in result.stderr
        assert restore.databases() == {"postgres", "glitchtip", LIVE, RESTORE}

    def test_terminate_sessions_ends_them_and_swaps(self, restore):
        restore.connect_session()

        result = restore.run(CONFIRM_SWAP="1", TERMINATE_SESSIONS="1")

        assert result.returncode == 0, result.stderr
        calls = restore.calls()
        terminate = next(i for i, c in enumerate(calls) if c.is_termination)
        swap = next(i for i, c in enumerate(calls) if c.is_swap)
        assert terminate < swap
        assert RESTORE not in restore.databases()

    def test_sessions_back_after_ending_them_block_the_swap(self, restore):
        # The app still runs and reconnects on its next request.
        restore.connect_session()
        restore.let_sessions_come_back()

        result = restore.run(CONFIRM_SWAP="1", TERMINATE_SESSIONS="1")

        assert result.returncode == 1
        assert any(call.is_termination for call in restore.calls())
        assert restore.renames() == []
        assert f"sessions keep connecting to {LIVE}" in result.stderr
        assert restore.databases() == {"postgres", "glitchtip", LIVE, RESTORE}

    def test_an_app_between_requests_blocks_the_swap(self, restore):
        # Not there at the start, then seen at the swap, gone at the next
        # look and back again: an app opening a session per request.
        restore.connect_session()
        restore.connect_now_and_then("-+-+")

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 1
        assert not any(call.is_termination for call in restore.calls())
        assert restore.renames() == []
        assert f"sessions keep connecting to {LIVE}" in result.stderr
        assert restore.databases() == {"postgres", "glitchtip", LIVE, RESTORE}

    def test_an_app_seen_only_while_watching_blocks_the_swap(self, restore):
        # Between two requests at the first looks, then connected again.
        restore.connect_session()
        restore.connect_now_and_then("--+")

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 1
        assert restore.renames() == []
        assert f"sessions keep connecting to {LIVE}" in result.stderr
        assert restore.databases() == {"postgres", "glitchtip", LIVE, RESTORE}

    def test_a_brief_session_that_ends_does_not_block_the_swap(self, restore):
        # Seen once at the swap, like the ledger cron's, and not again.
        restore.connect_session()
        restore.connect_now_and_then("-+-")

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert len(restore.renames()) == 1
        assert RESTORE not in restore.databases()

    def test_an_autovacuum_worker_does_not_hold_up_the_swap(self, restore):
        restore.connect_session(row=AUTOVACUUM, backend_type="autovacuum worker")

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert AUTOVACUUM not in result.stderr
        assert not any(call.is_termination for call in restore.calls())
        assert len(restore.renames()) == 1
        assert RESTORE not in restore.databases()


class TestTheLedgerBeforeTheSwap:
    @pytest.mark.parametrize("with_session", [False, True])
    def test_it_is_refreshed_again_right_before_the_swap(self, restore, with_session):
        env = {"CONFIRM_SWAP": "1"}
        if with_session:
            restore.connect_session()
            env["TERMINATE_SESSIONS"] = "1"

        result = restore.run(**env)

        assert result.returncode == 0, result.stderr
        calls = restore.calls()
        first, second = restore.ledger_refreshes()
        replay = next(i for i, c in enumerate(calls) if c.file)
        swap = next(i for i, c in enumerate(calls) if c.is_swap)
        last_check = max(
            i for i, c in enumerate(calls) if c.is_session_check or c.is_termination
        )
        assert first < replay < last_check < second < swap

    def test_a_failed_refresh_refuses_the_swap(self, restore):
        restore.fail_ledger_refresh(2)

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 1
        assert len(restore.ledger_refreshes()) == 2
        assert restore.renames() == []
        assert "could not refresh the GDPR deletion ledger" in result.stderr
        assert restore.databases() == {"postgres", "glitchtip", LIVE, RESTORE}

    def test_a_live_database_it_never_could_read_still_swaps(self, restore):
        restore.fail_ledger_refresh(1)
        restore.fail_ledger_refresh(2)

        result = restore.run(CONFIRM_SWAP="1")

        assert result.returncode == 0, result.stderr
        assert len(restore.ledger_refreshes()) == 2
        assert len(restore.renames()) == 1
        assert "before the swap either" in result.stderr
