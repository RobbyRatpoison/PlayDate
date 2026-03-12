#!/usr/bin/env bash
# PlayDate — launches the GUI uninstaller (no terminal window)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$DIR/uninstall.py"
