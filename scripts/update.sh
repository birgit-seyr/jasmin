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

# ── 3. deploy ────────────────────────────────────────────────────────────────
exec ./scripts/deploy.sh
