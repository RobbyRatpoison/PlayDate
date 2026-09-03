#!/bin/sh
# On a Steam Deck launched as a Steam shortcut, block WebKitGTK/libmanette
# from grabbing the built-in controller's hidraw node (which disables its
# firmware lizard-mode emulation and fights Steam Input -- doubled/dropped
# input in the Steam overlay). PlayDate reads Steam's virtual pad via evdev
# instead (gamepad_reader.py). Harmless everywhere else, so only armed here.
if [ "$SteamDeck" = "1" ] && [ -n "$SteamAppId" ] && [ -f /app/lib/playdate/libnohidraw.so ]; then
    LD_PRELOAD="/app/lib/playdate/libnohidraw.so${LD_PRELOAD:+:$LD_PRELOAD}"
    export LD_PRELOAD
fi
# PD_SRC_DIR (dev only): run from an rsync'd working tree so app-code changes
# don't need a CI flatpak rebuild. Unset in every real install.
exec python3 "${PD_SRC_DIR:-/app/share/playdate}/main.py" "$@"
