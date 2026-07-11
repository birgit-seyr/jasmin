#!/usr/bin/env bash
# =============================================================================
# update.sh — deploy the latest pushed commit on the prod host.
#
# THE answer to "I committed and pushed — now what?" is running this on the
# server:
#
#   ssh jasmin-prod
#   cd ~/jasmin-platform && ./scripts/update.sh
#
# It:
#   1. refuses to run if the working tree has unexpected local changes
#      (nginx/super_admin_allowed_ips.conf is the one EXPECTED server-local
#      edit — operator IPs live only on the server, never in git)
#   2. fetches + shows what's incoming, fast-forwards to origin/main
#   3. hands off to deploy.sh (env validation, image build, compose up,
#      wait-for-healthy, smoke test) — migrations run automatically in the
#      backend entrypoint on boot, forward-only
#
# Rollback story (small-scale): revert the commit locally, push, re-run this.
# Never reverse a shipped migration — write a forward fix (see CLAUDE.md).
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

die() { echo "❌ $*" >&2; exit 1; }

# ── 1. clean-tree guard ──────────────────────────────────────────────────────
# Tracked modifications block the pull (they'd conflict or get overwritten) —
# EXCEPT the super-admin IP allowlist, which is expected to differ on the
# server. Untracked files (.env, deploy.log, backups/*, certbots/linode.ini)
# are fine: git pull never touches them.
dirt="$(git status --porcelain --untracked-files=no \
        | grep -vE '^.M nginx/super_admin_allowed_ips\.conf$' || true)"
if [ -n "$dirt" ]; then
    echo "❌ Unexpected local changes on the server — resolve before updating:" >&2
    echo "$dirt" >&2
    echo "   (If these are hotfixes synced during an incident, either commit" >&2
    echo "   them from your workstation and push, or discard here with:" >&2
    echo "   git checkout -- <file>)" >&2
    exit 1
fi

# ── 2. fetch + fast-forward ──────────────────────────────────────────────────
git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
incoming="$(git log --oneline "HEAD..origin/${BRANCH}" | head -20)"
if [ -z "$incoming" ]; then
    echo "Already up to date with origin/${BRANCH}."
    read -r -p "Re-run deploy anyway (rebuild + restart)? [y/N] " yn
    case "$yn" in [Yy]*) ;; *) exit 0 ;; esac
else
    echo "Incoming commits:"
    echo "$incoming"
    git pull --ff-only origin "$BRANCH"
fi

# ── 2b. pre-deploy DB snapshot ───────────────────────────────────────────────
# A full logical dump of the (single, multi-schema) Postgres DB BEFORE the
# backend entrypoint applies migrations on the next boot. Migrations are
# forward-only + additive, but a live prod schema change always gets its own
# snapshot first. FAIL-CLOSED: if the dump can't be taken, we do NOT deploy.
#
# Skipped when postgres isn't running yet (a first-ever deploy has no data to
# lose — deploy.sh creates the DB). The scheduled ``backup`` service still does
# routine off-host backups; this is the extra "right before I migrate" one,
# kept locally under backups/ (gitignored).
PG_CID="$(docker compose ps -q postgres 2>/dev/null || true)"
if [ -n "$PG_CID" ] && \
   [ "$(docker inspect -f '{{.State.Running}}' "$PG_CID" 2>/dev/null)" = "true" ]; then
    mkdir -p backups
    SNAPSHOT="backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sql.gz"
    echo "[update] snapshotting DB -> ${SNAPSHOT}"
    if ! docker compose exec -T postgres \
            sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$SNAPSHOT"; then
        rm -f "$SNAPSHOT"
        die "pre-deploy DB snapshot FAILED — not deploying. Fix the dump and re-run."
    fi
    # pipefail catches a pg_dump crash; this catches a 0-byte write slipping through.
    [ -s "$SNAPSHOT" ] || die "pre-deploy snapshot is empty — not deploying."
    echo "[update] snapshot ok ($(du -h "$SNAPSHOT" | cut -f1))"
    # Retention (best-effort): keep the 10 most recent pre-deploy snapshots.
    ls -1t backups/pre-deploy-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f || true
else
    echo "[update] postgres not running — skipping pre-deploy snapshot (first deploy?)."
fi

# ── 3. deploy ────────────────────────────────────────────────────────────────
exec ./scripts/deploy.sh
