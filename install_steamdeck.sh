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

# Bootstrap the keyring update with signature checking disabled.
# Without this, pacman refuses to install archlinux-keyring because the
# existing keyring is too old to trust its signature — a chicken-and-egg
# problem after SteamOS system updates.
echo "==> Updating keyring packages (signature check bypassed for this step)..."
TMPCONF=$(mktemp /tmp/pacman-XXXXXX.conf)
sed 's/^SigLevel.*/SigLevel = Never/' /etc/pacman.conf > "$TMPCONF"
sudo pacman --config "$TMPCONF" -Sy --noconfirm archlinux-keyring
rm -f "$TMPCONF"

echo "==> Rebuilding pacman keyring with fresh keys..."
sudo rm -rf /etc/pacman.d/gnupg
sudo pacman-key --init
sudo pacman-key --populate archlinux holo

echo "==> Installing Python/WebKit dependencies..."
sudo pacman -S --needed --noconfirm python-gobject webkit2gtk

echo "==> Re-locking filesystem..."
sudo steamos-readonly enable

# ── Run installer ─────────────────────────────────────────────────────────────
echo ""
bash "$DIR/install.sh"
