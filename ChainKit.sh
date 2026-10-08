#!/bin/bash
# Starts the ChainKit window on Linux. Run ./setup.sh once first.
# Keep the terminal open while ChainKit runs; it shows the program's messages.
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
    echo "ChainKit is not set up yet: run ./setup.sh first, then ./ChainKit.sh again."
    exit 1
fi
exec ".venv/bin/python" -m chainkit gui
