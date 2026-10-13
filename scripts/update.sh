#!/usr/bin/env bash
# =============================================================================
# update.sh — deploy the latest pushed commit on the prod host, once CI passed.
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
#   2. fetches + shows what's incoming
#   3. asks GitHub whether CI (.github/workflows/ci.yml) passed for the exact
#      commit it is about to deploy: the tip of origin/main, or HEAD when
#      nothing is incoming. The newest CI run of that commit's push to main
#      decides, and only "success" goes on. A run still queued or running
#      (run this again once it's green), a failed or cancelled run, no run at
#      all, or no usable answer from GitHub stops the update before the
#      checkout moves
#   4. fast-forwards to exactly that commit, even if origin has moved on since
#      the fetch
#   5. hands off to deploy.sh (env validation, image build, an encrypted
#      snapshot of the database, compose up, wait-for-healthy, smoke test) —
#      migrations run automatically in the backend entrypoint on boot,
#      forward-only
#
# Flags:
#   --skip-ci-check   skip step 3 and deploy whatever CI made of the commit,
#                     with a warning. For an emergency only, such as GitHub
#                     being down. SKIP_CI_CHECK=1 in the environment does the
#                     same.
#   -h, --help        print this text
#
# Rollback: ./scripts/rollback.sh switches back to one of the last releases
# whose migrations the database already has. Then revert or fix forward,
# push, and re-run this once the fix's CI run is green. Never reverse a
# shipped migration — write a forward fix (see CLAUDE.md).
# =============================================================================
set -euo pipefail

# Prints the header above.
usage() { awk 'NR > 2 { if (/^# ====/) exit; sub(/^# ?/, ""); print }' "$0"; }

case "${SKIP_CI_CHECK:-0}" in
    0) SKIP_CI=0 ;;
    1) SKIP_CI=1 ;;
    *) echo "SKIP_CI_CHECK must be 1 (skip the CI check) or unset, not '${SKIP_CI_CHECK}'." >&2
       exit 2 ;;
esac
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-ci-check) SKIP_CI=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1 (see --help)" >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

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

# ── 2. fetch + pick the commit to deploy ─────────────────────────────────────
git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
# NB: cap with git's own -n, NOT `| head -20`. Under `set -euo pipefail`, head
# closing the pipe after 20 lines sends SIGPIPE to a still-writing git log
# (>20 incoming commits) → exit 141 → the whole script aborts silently here.
incoming="$(git log --oneline -n 20 "HEAD..origin/${BRANCH}")"
if [ -z "$incoming" ]; then
    echo "Already up to date with origin/${BRANCH}."
    read -r -p "Re-run deploy anyway (rebuild + restart)? [y/N] " yn
    case "$yn" in [Yy]*) ;; *) exit 0 ;; esac
    TARGET="$(git rev-parse HEAD)"
else
    echo "Incoming commits:"
    echo "$incoming"
    TARGET="$(git rev-parse "origin/${BRANCH}")"
fi

# ── 3. CI gate ───────────────────────────────────────────────────────────────
# GitHub's REST API answers for this public repository without a token, 60
# requests an hour per IP. Only runs that a push to main started count: a
# pull_request run tests the merge with main as it was then, not this commit.
# The newest of them decides, since pushing the same commit again starts a new
# run. Anything but "success" stops the update here, before the checkout moves.

# The GitHub owner/repo of remote URL $1, in each form git takes:
# https://github.com/o/r.git, git@github.com:o/r.git, ssh://git@github.com/o/r
# — or with a host alias from ~/.ssh/config in place of github.com.
github_repo() {
    local path
    case "$1" in
        *://*) path="${1#*://}"; path="${path#*/}" ;;
        *:*) path="${1#*:}" ;;
        *) return 1 ;;
    esac
    path="${path%/}"
    path="${path%.git}"
    [[ "$path" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || return 1
    echo "$path"
}

# Reads the API's list of CI runs on stdin and prints "<status> <conclusion>
# <url>" of the newest run that a push of commit $1 started ("-" for null),
# or nothing when there is none. Fails on anything but one complete list of
# runs. The host has neither jq nor Python: grep cuts the JSON into tokens,
# one per line (strings, numbers and literals, punctuation), and awk walks
# them with a stack of the open objects and arrays, so a key counts only on
# the run itself, never on an object nested in it or inside a string.
newest_ci_run() {
    LC_ALL=C grep -oE '"([^"\\]|\\.)*"|[][{}:,]|[-+.0-9A-Za-z]+' \
        | LC_ALL=C awk -v sha="\"$1\"" '
            function text(token) {
                if (token == "" || token == "null") return "-"
                if (token ~ /^".*"$/) token = substr(token, 2, length(token) - 2)
                gsub(/[^A-Za-z0-9_.:\/-]/, "?", token)
                return token
            }
            # True inside one element of the top-level "workflow_runs" array.
            function in_run() {
                return depth == 3 && kind[3] == "{" && kind[2] == "[" &&
                    kind[1] == "{" && key[1] == "\"workflow_runs\""
            }
            ended { broken = 1; exit }
            $0 == "{" || $0 == "[" {
                kind[++depth] = $0
                key[depth] = ""
                want_key[depth] = ($0 == "{")
                if (in_run()) id = status = conclusion = event = head_sha = url = ""
                next
            }
            !depth { broken = 1; exit }
            $0 == "}" || $0 == "]" {
                if (kind[depth] != ($0 == "}" ? "{" : "[")) { broken = 1; exit }
                if (in_run() && event == "\"push\"" && head_sha == sha && id + 0 > newest + 0) {
                    newest = id
                    run = text(status) " " text(conclusion) " " text(url)
                }
                if (depth == 2 && kind[2] == "[" && kind[1] == "{" && key[1] == "\"workflow_runs\"")
                    listed = 1
                if (--depth == 0) ended = 1
                next
            }
            $0 == "," { want_key[depth] = (kind[depth] == "{"); next }
            $0 == ":" { want_key[depth] = 0; next }
            want_key[depth] { key[depth] = $0; next }
            in_run() {
                if (key[3] == "\"id\"") id = $0
                else if (key[3] == "\"status\"") status = $0
                else if (key[3] == "\"conclusion\"") conclusion = $0
                else if (key[3] == "\"event\"") event = $0
                else if (key[3] == "\"head_sha\"") head_sha = $0
                else if (key[3] == "\"html_url\"") url = $0
            }
            END {
                if (broken || !ended || !listed) exit 1
                if (run != "") print run
            }'
}

# Stops the update before the checkout moves: $1 says why, any further
# arguments what to do about it, a line each.
refuse_deploy() {
    echo "❌ Not deploying ${TARGET:0:7}: $1" >&2
    shift
    [ $# -eq 0 ] || printf '   %s\n' "$@" >&2
    exit 1
}

# The same when GitHub gave no verdict, the case the override is for.
refuse_unknown() {
    refuse_deploy "$@" \
        "If GitHub itself is down and the deploy can't wait: ./scripts/update.sh --skip-ci-check"
}

REPO_SLUG="$(github_repo "$(git config --get remote.origin.url || true)")" || REPO_SLUG=""
if [ "$SKIP_CI" -eq 1 ]; then
    cat >&2 <<EOF

⚠️  ==========================================================================
⚠️  CI CHECK SKIPPED: deploying ${TARGET:0:7} without knowing whether CI passed
⚠️  for it. Look at its run as soon as GitHub answers, and fix forward if it
⚠️  is red: https://github.com/${REPO_SLUG:-<owner>/<repo>}/commit/${TARGET}
⚠️  ==========================================================================

EOF
else
    [ -n "$REPO_SLUG" ] \
        || refuse_unknown "origin's URL names no GitHub repository to ask about CI (git remote -v)."
    echo "Asking GitHub whether CI passed for ${TARGET:0:7}"
    CI_RUNS_URL="https://api.github.com/repos/${REPO_SLUG}/actions/workflows/ci.yml/runs?head_sha=${TARGET}&event=push&per_page=100"
    # -w puts the HTTP status on a last line of its own, after the body.
    if ! response="$(curl -sSL --max-time 30 -w '\n%{http_code}' \
            -H 'Accept: application/vnd.github+json' \
            -H 'X-GitHub-Api-Version: 2022-11-28' "$CI_RUNS_URL")"; then
        refuse_unknown "no answer from the GitHub API, so whether CI passed is unknown."
    fi
    http_code="${response##*$'\n'}"
    body="${response%$'\n'*}"
    [ "$http_code" = 200 ] || refuse_unknown \
        "the GitHub API answered HTTP ${http_code}: $(LC_ALL=C tr -cd '[:print:]' <<< "${body:0:300}")"
    run="$(newest_ci_run "$TARGET" <<< "$body")" \
        || refuse_unknown "the GitHub API's answer isn't a list of CI runs."
    read -r ci_status ci_conclusion run_url <<< "${run:-none - -}"
    case "${ci_status}/${ci_conclusion}" in
        completed/success)
            echo "CI passed for ${TARGET:0:7}: ${run_url}" ;;
        completed/cancelled)
            refuse_deploy "its CI run was cancelled: ${run_url}" \
                "A push to main cancels the run of the commit before it: run this again" \
                "to pick up the newer commit, or re-run the cancelled run on GitHub." ;;
        completed/*)
            refuse_deploy "its CI run ended in '${ci_conclusion}': ${run_url}" \
                "Fix it forward and push; this deploys the fix once CI passes." ;;
        queued/* | in_progress/* | waiting/* | requested/* | pending/*)
            refuse_deploy "its CI run is still ${ci_status}: ${run_url}" \
                "Run ./scripts/update.sh again once it is green." ;;
        none/*)
            refuse_unknown "GitHub has no CI run for it." \
                "A push to main starts one within seconds, so try again in a minute. A" \
                "commit pushed with [skip ci] in its message, or never to main, gets none." ;;
        *)
            refuse_unknown "its CI run is '${ci_status}', a state update.sh doesn't know: ${run_url}" ;;
    esac
fi

# ── 4. fast-forward ──────────────────────────────────────────────────────────
# To the commit CI passed, not to wherever origin/main has moved since.
if [ -n "$incoming" ]; then
    git merge --ff-only "$TARGET"
fi

# ── 5. deploy ────────────────────────────────────────────────────────────────
exec ./scripts/deploy.sh
