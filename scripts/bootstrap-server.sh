#!/usr/bin/env bash
# =============================================================================
# bootstrap-server.sh — one-shot hardening for a fresh Ubuntu 24.04 Linode.
#
# Idempotent: safe to re-run. Does everything Phase 1 of the go-live runbook
# describes:
#   1. create a non-root sudo user (key-login, passwordless sudo)
#   2. copy root's SSH key to that user
#   3. install Docker Engine + compose plugin
#   4. unattended-upgrades (auto security patches)
#   5. fail2ban (ban brute-force SSH)
#   6. ufw (allow SSH/80/443, deny the rest) — belt-and-braces behind the
#      Linode Cloud Firewall
#   7. SSH hardening (key-only, no root login) — SKIPPED if the new user has no
#      authorized_keys yet, so it can never lock you out
#
# Run as root on the box:
#   ssh root@<server-ip>
#   git clone <repo> jasmin-platform && cd jasmin-platform    # or scp this file
#   ./scripts/bootstrap-server.sh --user bia
#
# ESCAPE HATCH: if SSH ever breaks, Linode's Lish web console (Cloud Manager →
# your Linode → "Launch LISH Console") always gets you in to fix it.
# =============================================================================
set -euo pipefail

NEW_USER=""
HARDEN_SSH=1

while [ $# -gt 0 ]; do
    case "$1" in
        --user) NEW_USER="${2:?}"; shift 2 ;;
        --no-ssh-harden) HARDEN_SSH=0; shift ;;
        -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then
    echo "❌ Run as root (you're on a fresh box): ssh root@<ip>, then re-run." >&2
    exit 1
fi
if [ -z "$NEW_USER" ] && [ -t 0 ]; then
    read -r -p "Non-root username to create (e.g. bia): " NEW_USER
fi
: "${NEW_USER:?--user is required}"

log() { echo "[bootstrap] $*"; }

# ── 1. non-root sudo user ────────────────────────────────────────────────────
if id "$NEW_USER" >/dev/null 2>&1; then
    log "user '$NEW_USER' already exists — skipping create"
else
    log "creating user '$NEW_USER'"
    adduser --disabled-password --gecos "" "$NEW_USER"
fi
usermod -aG sudo "$NEW_USER"
# Passwordless sudo so key-only login can still run sudo (no password exists).
# Single-admin box behind key-only SSH + firewall; tighten later if you add ops.
printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$NEW_USER" > "/etc/sudoers.d/90-${NEW_USER}"
chmod 440 "/etc/sudoers.d/90-${NEW_USER}"
visudo -cf "/etc/sudoers.d/90-${NEW_USER}" >/dev/null

# ── 2. copy root's SSH key to the new user ───────────────────────────────────
USER_HOME="$(getent passwd "$NEW_USER" | cut -d: -f6)"
if [ -s /root/.ssh/authorized_keys ]; then
    log "copying root's authorized_keys to $NEW_USER"
    install -d -m 700 -o "$NEW_USER" -g "$NEW_USER" "${USER_HOME}/.ssh"
    install -m 600 -o "$NEW_USER" -g "$NEW_USER" \
        /root/.ssh/authorized_keys "${USER_HOME}/.ssh/authorized_keys"
else
    log "WARN: /root/.ssh/authorized_keys is missing/empty — add your key to"
    log "      ${USER_HOME}/.ssh/authorized_keys before SSH hardening runs."
fi

export DEBIAN_FRONTEND=noninteractive
log "apt update"
apt-get update -qq

# ── 3. Docker Engine + compose plugin ────────────────────────────────────────
if command -v docker >/dev/null 2>&1; then
    log "docker already installed — skipping"
else
    log "installing Docker (get.docker.com)"
    curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$NEW_USER"

# ── 4 + 5. unattended-upgrades + fail2ban ────────────────────────────────────
log "installing unattended-upgrades + fail2ban"
apt-get install -y -qq unattended-upgrades fail2ban
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
systemctl enable --now fail2ban >/dev/null 2>&1 || true

# ── 6. ufw firewall (allow SSH/80/443, deny rest) ────────────────────────────
log "configuring ufw"
apt-get install -y -qq ufw
ufw allow OpenSSH        >/dev/null
ufw allow 80/tcp         >/dev/null
ufw allow 443/tcp        >/dev/null
ufw default deny incoming  >/dev/null
ufw default allow outgoing >/dev/null
ufw --force enable       >/dev/null

# ── 7. SSH hardening (guarded) ───────────────────────────────────────────────
if [ "$HARDEN_SSH" -eq 1 ]; then
    if [ -s "${USER_HOME}/.ssh/authorized_keys" ]; then
        log "hardening SSH (key-only, no root login)"
        cat > /etc/ssh/sshd_config.d/99-jasmin-hardening.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
EOF
        if sshd -t; then
            systemctl restart ssh || systemctl restart sshd
            log "SSH hardened. Open a NEW terminal and confirm: ssh ${NEW_USER}@<ip>"
        else
            log "WARN: sshd config test failed — removing hardening drop-in"
            rm -f /etc/ssh/sshd_config.d/99-jasmin-hardening.conf
        fi
    else
        log "WARN: skipping SSH hardening — $NEW_USER has no authorized_keys."
        log "      Add your key, then re-run to harden (avoids lock-out)."
    fi
fi

echo ""
echo "✅ Server bootstrapped."
echo "   • Log in from now on as:  ssh ${NEW_USER}@<server-ip>"
echo "   • Log out + back in once so the 'docker' group applies to ${NEW_USER}."
echo "   • Then: cd into the repo, run scripts/init-env.sh, then scripts/deploy.sh"
echo "   • Escape hatch if SSH breaks: Linode Cloud Manager → Launch LISH Console"
