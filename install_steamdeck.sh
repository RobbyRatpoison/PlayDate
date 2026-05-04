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

echo "==> Initialising pacman keyring..."
sudo pacman-key --init
sudo pacman-key --populate archlinux

echo "==> Installing Python/WebKit dependencies..."
sudo pacman -S --noconfirm python-gobject webkit2gtk

echo "==> Re-locking filesystem..."
sudo steamos-readonly enable

# ── Run installer ─────────────────────────────────────────────────────────────
echo ""
bash "$DIR/install.sh"
