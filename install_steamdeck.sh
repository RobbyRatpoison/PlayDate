#!/usr/bin/env bash
# PlayDate — Steam Deck installer / repair script
#
# Run once to install. Re-run after a SteamOS system update, which wipes
# installed packages and breaks PlayDate.
#
# Usage:
#   chmod +x install_steamdeck.sh && ./install_steamdeck.sh

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Check sudo password ───────────────────────────────────────────────────────
# SteamOS ships with no password set by default; sudo will not work until one
# is configured.
if passwd -S "$(whoami)" 2>/dev/null | grep -q ' NP '; then
    echo "Error: no password is set for your account."
    echo ""
    echo "Set one first with:  passwd"
    echo "Then re-run this script."
    exit 1
fi

# ── Install Python/WebKit dependencies ───────────────────────────────────────
echo "==> Unlocking read-only filesystem..."
sudo steamos-readonly disable

echo "==> Clearing cached packages..."
sudo rm -rf /var/cache/pacman/pkg/*.zst 2>/dev/null || true

# After a SteamOS system update, steamos-keyring may not be installed, so
# pacman-key --populate holo is a no-op and SteamOS-signed packages are
# rejected as untrusted. Fix: patch SigLevel=Never into the real pacman.conf
# (no --config arg, which SteamOS pacman may ignore), install the keyring
# packages, then populate properly. Do NOT nuke /etc/pacman.d/gnupg before
# steamos-keyring is installed or --populate holo will have nothing to read.
echo "==> Syncing package database..."
sudo pacman -Sy

# The SteamOS CI builder key is already in the keyring but marked as
# unknown trust after a system update. Locally signing it is enough —
# no keyring package needed.
echo "==> Trusting SteamOS signing keys..."
FPRINTS=$(sudo gpg --homedir /etc/pacman.d/gnupg --list-keys --with-colons \
    "@steamos.cloud" 2>/dev/null | grep '^fpr' | cut -d: -f10)
if [ -z "$FPRINTS" ]; then
    echo "    Warning: no @steamos.cloud keys found in keyring — trying populate..."
    sudo pacman-key --populate archlinux
else
    for fpr in $FPRINTS; do
        echo "    lsign $fpr"
        sudo pacman-key --lsign-key "$fpr"
    done
fi

echo "==> Installing Python/WebKit dependencies..."
sudo pacman -S --needed --noconfirm python-gobject webkit2gtk

echo "==> Re-locking filesystem..."
sudo steamos-readonly enable

# ── Run installer ─────────────────────────────────────────────────────────────
echo ""
bash "$DIR/launch.sh"
