#!/usr/bin/env bash
# =============================================================================
# Run CI's secret scan locally, over the files a commit would carry.
#
# Same image, version and config as the "Secret scan (gitleaks)" job in
# .github/workflows/ci.yml and the gitleaks pre-commit hook. CI scans a fresh
# checkout; a plain `gitleaks dir .` here would also read .env, logs, e2e login
# states and the other gitignored files that never reach the repository, and
# flag them. So this copies the tracked files plus the untracked ones git would
# add (not ignored) into a temporary directory and scans that.
#
# Usage: scripts/secret_scan.sh     (or: make secrets)
# =============================================================================
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# A tracked file deleted in the working tree is still listed; skip it.
git ls-files -z --cached --others --exclude-standard \
  | while IFS= read -r -d '' path; do
      [ -e "$path" ] && printf '%s\0' "$path"
    done \
  | tar --null -T - -cf - \
  | tar -xf - -C "$tmp"

docker run --rm -v "$tmp:/repo" ghcr.io/gitleaks/gitleaks:v8.28.0 \
  dir /repo --config=/repo/.gitleaks.toml --no-banner --redact
