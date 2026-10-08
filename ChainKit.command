#!/bin/bash
# Starts the ChainKit window on macOS (double-click it in Finder). Run setup.command once first.
# Keep this Terminal window open while ChainKit runs; it shows the program's messages.
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
    echo "ChainKit is not set up yet: double-click setup.command first, then ChainKit.command again."
    [ -t 0 ] && read -r -p "Press Enter to close this window..." _
    exit 1
fi
exec ".venv/bin/python" -m chainkit gui
