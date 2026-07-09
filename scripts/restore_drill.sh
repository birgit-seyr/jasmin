#!/usr/bin/env bash
# Restore drill — restores a backup into a throwaway sandbox postgres
# and writes a per-table row-count comparison vs the live prod DB.
#
# Usage:
#     ./scripts/restore_drill.sh                       # newest file in ./backups/
#     ./scripts/restore_drill.sh ./backups/foo.sql
#     ./scripts/restore_drill.sh ./backups/foo.sql.gz.gpg
#
# Requires:
#     - docker
#     - the prod stack running (we read POSTGRES_USER/DB from its env and
#       query the live DB for the comparison column)
#     - for .sql.gz.gpg files: BACKUP_ENCRYPTION_KEY in the environment
#       (sourced from .env on prod, kept in your password manager)
#
# Output:
#     docs/code_audit/security/restore-drills/YYYY-MM-DD.md  (markdown table; sign-off
#                                         block appended by the operator)
#
# Safety:
#     The sandbox container is fully isolated (no host port, default
#     bridge network only) and torn down at the end. Prod is read-only
#     for the row-count query — no writes anywhere near it.
#
# See docs/code_audit/security/restore-drill.md for the runbook this script implements.

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
SANDBOX_CONTAINER="jasmin-restore-sandbox"
SANDBOX_DB="jasmin_sandbox"
SANDBOX_USER="jasmin_sandbox"
# Passphrase is throwaway — the container lives for ~30s and never
# accepts a connection from outside docker exec.
SANDBOX_PASSWORD="sandbox_$(date +%s)_$RANDOM"
PROD_POSTGRES_CONTAINER="${PROD_POSTGRES_CONTAINER:-$(docker compose ps -q postgres 2>/dev/null || true)}"
OUTPUT_DIR="docs/code_audit/security/restore-drills"
OUTPUT_FILE="${OUTPUT_DIR}/$(date +%Y-%m-%d).md"

# ── Argument: backup file ──────────────────────────────────────────────────
BACKUP="${1:-}"
if [ -z "$BACKUP" ]; then
    # Pick the newest backup under ./backups/. ``ls -t`` sorts by mtime
    # descending; redirect stderr because either glob may not match.
    BACKUP="$(ls -t backups/*.sql.gz.gpg backups/*.sql 2>/dev/null | head -n 1 || true)"
fi

if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
    echo "ERROR: no backup file found." >&2
    echo "Pass one explicitly: $0 <path-to-backup>" >&2
    echo "Or put one under ./backups/ and re-run." >&2
    exit 1
fi

if [ -z "$PROD_POSTGRES_CONTAINER" ]; then
    echo "ERROR: prod postgres container not found. Is the stack up?" >&2
    echo "(Looked for: docker compose ps -q postgres)" >&2
    exit 1
fi

# ── Prep output dir + header ───────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
BACKUP_MTIME=$(date -r "$BACKUP" '+%Y-%m-%d %H:%M:%S')

{
    echo "# Restore drill — $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "- **Backup file:** \`$BACKUP\`"
    echo "- **Backup mtime:** $BACKUP_MTIME"
    echo "- **Operator:** $(whoami)"
    echo "- **Host:** $(hostname)"
    echo ""
} > "$OUTPUT_FILE"

echo "Restore drill starting — log: $OUTPUT_FILE"

# ── Cleanup hook (always runs, even on failure) ────────────────────────────
cleanup() {
    if docker ps -q --filter "name=^${SANDBOX_CONTAINER}$" | grep -q .; then
        echo "Tearing down sandbox container..."
        docker stop "$SANDBOX_CONTAINER" > /dev/null 2>&1 || true
        docker rm "$SANDBOX_CONTAINER" > /dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# ── Spin up sandbox postgres ───────────────────────────────────────────────
echo "Starting sandbox postgres ($SANDBOX_CONTAINER)..."
docker run -d --rm \
    --name "$SANDBOX_CONTAINER" \
    -e POSTGRES_DB="$SANDBOX_DB" \
    -e POSTGRES_USER="$SANDBOX_USER" \
    -e POSTGRES_PASSWORD="$SANDBOX_PASSWORD" \
    postgres:15-alpine > /dev/null

# Wait for accept-connections. ``pg_isready`` returns 0 once it's ready.
for _ in $(seq 1 30); do
    if docker exec "$SANDBOX_CONTAINER" pg_isready -U "$SANDBOX_USER" -d "$SANDBOX_DB" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! docker exec "$SANDBOX_CONTAINER" pg_isready -U "$SANDBOX_USER" -d "$SANDBOX_DB" > /dev/null 2>&1; then
    echo "ERROR: sandbox postgres didn't become ready in 30s" >&2
    exit 1
fi

# ── Restore ────────────────────────────────────────────────────────────────
echo "Restoring backup into sandbox (this may take a minute)..."
case "$BACKUP" in
    *.sql.gz.gpg)
        if [ -z "${BACKUP_ENCRYPTION_KEY:-}" ]; then
            echo "ERROR: BACKUP_ENCRYPTION_KEY not set — cannot decrypt $BACKUP" >&2
            echo "Source .env on the prod host or paste the passphrase from your password manager." >&2
            exit 1
        fi
        gpg --batch --yes --decrypt --passphrase "$BACKUP_ENCRYPTION_KEY" "$BACKUP" \
            | gunzip \
            | docker exec -i "$SANDBOX_CONTAINER" \
                psql -v ON_ERROR_STOP=1 --single-transaction \
                -U "$SANDBOX_USER" -d "$SANDBOX_DB" \
                > /dev/null
        ;;
    *.sql)
        docker exec -i "$SANDBOX_CONTAINER" \
            psql -v ON_ERROR_STOP=1 --single-transaction \
            -U "$SANDBOX_USER" -d "$SANDBOX_DB" \
            < "$BACKUP" > /dev/null
        ;;
    *)
        echo "ERROR: unsupported backup format: $BACKUP" >&2
        echo "Supported: .sql, .sql.gz.gpg" >&2
        exit 1
        ;;
esac

echo "Restore complete. Running row-count comparison..."

# ── Read prod creds (already-exported env on prod, fallback to compose env)
PROD_USER="${POSTGRES_USER:-$(docker exec "$PROD_POSTGRES_CONTAINER" printenv POSTGRES_USER)}"
PROD_DB="${POSTGRES_DB:-$(docker exec "$PROD_POSTGRES_CONTAINER" printenv POSTGRES_DB)}"

# ── Enumerate tables + emit markdown row-count comparison ─────────────────
ENUMERATE_SQL="SELECT schemaname || '.' || tablename
               FROM pg_tables
               WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
               ORDER BY schemaname, tablename"

{
    echo "## Row-count comparison"
    echo ""
    echo "| Schema | Table | Sandbox rows | Prod rows | Diff (prod − sandbox) |"
    echo "|---|---|---:|---:|---:|"
} >> "$OUTPUT_FILE"

TOTAL_TABLES=0
LARGE_DIFFS=0

while IFS= read -r qualified; do
    [ -z "$qualified" ] && continue
    schema="${qualified%%.*}"
    table="${qualified#*.}"
    TOTAL_TABLES=$((TOTAL_TABLES + 1))

    sandbox_count=$(docker exec "$SANDBOX_CONTAINER" \
        psql -U "$SANDBOX_USER" -d "$SANDBOX_DB" -t -A \
        -c "SELECT count(*) FROM \"$schema\".\"$table\";" 2>/dev/null || echo "ERR")

    prod_count=$(docker exec "$PROD_POSTGRES_CONTAINER" \
        psql -U "$PROD_USER" -d "$PROD_DB" -t -A \
        -c "SELECT count(*) FROM \"$schema\".\"$table\";" 2>/dev/null || echo "n/a")

    if [ "$prod_count" = "n/a" ] || [ "$prod_count" = "ERR" ] || [ "$sandbox_count" = "ERR" ]; then
        diff="n/a"
    else
        diff=$((prod_count - sandbox_count))
        # Flag tables whose diff is suspiciously large — operator should
        # eyeball these in the sign-off.
        abs_diff=${diff#-}
        if [ "$abs_diff" -gt 1000 ]; then
            LARGE_DIFFS=$((LARGE_DIFFS + 1))
        fi
        # Prefix positive diffs with + for readability.
        if [ "$diff" -gt 0 ]; then
            diff="+$diff"
        fi
    fi

    printf "| %s | %s | %s | %s | %s |\n" \
        "$schema" "$table" "$sandbox_count" "$prod_count" "$diff" >> "$OUTPUT_FILE"
done < <(docker exec "$SANDBOX_CONTAINER" \
    psql -U "$SANDBOX_USER" -d "$SANDBOX_DB" -t -A -c "$ENUMERATE_SQL")

{
    echo ""
    echo "## Summary"
    echo ""
    echo "- Tables compared: **$TOTAL_TABLES**"
    echo "- Tables with diff > ±1000 rows: **$LARGE_DIFFS** (eyeball these in sign-off)"
    echo ""
    echo "## Sign-off"
    echo ""
    echo "<!-- Edit the block below after reviewing the diff above. -->"
    echo "- **Outcome:** PASS | FAIL"
    echo "- **Notes:**"
    echo ""
} >> "$OUTPUT_FILE"

echo ""
echo "Drill complete."
echo "Log: $OUTPUT_FILE"
echo ""
echo "Next steps:"
echo "  1. Review the row-count table"
echo "  2. Append the sign-off block (set Outcome: PASS / FAIL + notes)"
echo "  3. git add + commit the log as the audit artifact"
