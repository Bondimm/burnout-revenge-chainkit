#!/bin/bash
# One-time setup on macOS (double-click it in Finder; also works on Linux): creates a private Python environment
# (.venv) with the packages ChainKit needs. Safe to run again (repairs or updates the environment).
# CHAINKIT_NO_PAUSE=1 (or CI=true) skips the final "Press Enter" prompt.

cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
PYURL="https://www.python.org/downloads/macos/"

finish() {
    echo
    if [ -z "${CHAINKIT_NO_PAUSE:-}" ] && [ -z "${CI:-}" ] && [ -t 0 ]; then
        read -r -p "Press Enter to close this window..." _
    fi
    exit "$1"
}

fail() {
    echo
    echo "ERROR: $*"
    finish 1
}

py_ok() {  # python >= 3.11?
    "$1" -c "import sys; sys.exit(sys.version_info[:2] < (3, 11))" >/dev/null 2>&1
}

find_python() {
    local cand path
    for cand in python3 python3.14 python3.13 python3.12 python3.11 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.11/bin/python3; do
        path="$(command -v "$cand" 2>/dev/null)" || continue
        # Apple's /usr/bin/python3 is only a stub that pops up an installer when the Command Line Tools are missing
        if [ "$path" = "/usr/bin/python3" ] && [ "$(uname -s)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
            continue
        fi
        if py_ok "$path"; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

if [ -e ".venv/bin/python" ] && ! py_ok ".venv/bin/python"; then
    echo "The existing .venv does not work with Python 3.11+ - creating it again..."
    rm -rf ".venv"
fi
if [ ! -e ".venv/bin/python" ]; then
    PY="$(find_python)" || {
        echo "Python 3.11 or newer is required."
        command -v python3 >/dev/null 2>&1 && [ "$(command -v python3)" != "/usr/bin/python3" ] && python3 --version
        echo "Install it from $PYURL (or: brew install python), then run setup.command again."
        finish 1
    }
    echo "Creating Python environment with $PY ($("$PY" --version 2>&1))..."
    "$PY" -m venv ".venv" || fail "Could not create the Python environment in \"$HERE/.venv\"."
fi
echo "Installing Python packages..."
.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install --prefer-binary -r requirements.txt ||
    fail "Installing the Python packages failed - see the messages above.
Check the internet connection, then run setup.command again."

echo
echo "Setup complete. Start ChainKit with ChainKit.command"
finish 0
