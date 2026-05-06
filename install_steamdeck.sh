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

# After a SteamOS system update the keyring trust database is broken and
# pacman rejects every package signature. We use a temporary pacman.conf
# with SigLevel=Never to install everything we need, then rebuild the
# keyring so normal pacman usage works afterwards.
TMPCONF=$(mktemp /tmp/pacman-XXXXXX.conf)
sed 's/SigLevel\s*=.*/SigLevel = Never/g' /etc/pacman.conf > "$TMPCONF"

echo "==> Syncing package database..."
sudo pacman --config "$TMPCONF" -Sy

echo "==> Installing Python/WebKit dependencies..."
sudo pacman --config "$TMPCONF" -S --needed --noconfirm \
    archlinux-keyring python-gobject webkit2gtk

rm -f "$TMPCONF"

echo "==> Rebuilding pacman keyring (for future pacman use)..."
sudo rm -rf /etc/pacman.d/gnupg
sudo pacman-key --init
sudo pacman-key --populate archlinux holo

echo "==> Re-locking filesystem..."
sudo steamos-readonly enable

# ── Run installer ─────────────────────────────────────────────────────────────
echo ""
bash "$DIR/install.sh"
