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
exec python3 /app/share/playdate/main.py "$@"
