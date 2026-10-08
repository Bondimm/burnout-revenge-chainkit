#!/bin/bash
# One-time setup on Linux (run ./setup.sh in a terminal): creates a private Python environment (.venv) with
# the packages ChainKit needs. Safe to run again (repairs or updates the environment).
# CHAINKIT_NO_PAUSE=1 (or CI=true) skips the final "Press Enter" prompt.

cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

finish() {
    echo
    if [ -z "${CHAINKIT_NO_PAUSE:-}" ] && [ -z "${CI:-}" ] && [ -t 0 ] && [ -t 1 ]; then
        read -r -p "Press Enter to close..." _
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
    for cand in python3 python3.14 python3.13 python3.12 python3.11 python; do
        path="$(command -v "$cand" 2>/dev/null)" || continue
        if py_ok "$path"; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

install_hint() {
    echo "  Debian / Ubuntu / Mint:  sudo apt install python3 python3-venv python3-pip"
    echo "  Fedora / RHEL:           sudo dnf install python3 python3-pip"
    echo "  Arch / Manjaro:          sudo pacman -S python python-pip"
    echo "  openSUSE:                sudo zypper install python3 python3-pip"
}

# ---------------------------------------------------------------- Python environment
if [ -e ".venv/bin/python" ] && ! py_ok ".venv/bin/python"; then
    echo "The existing .venv does not work with Python 3.11+ - creating it again..."
    rm -rf ".venv"
fi
if [ ! -e ".venv/bin/python" ]; then
    PY="$(find_python)" || {
        echo "Python 3.11 or newer is required."
        command -v python3 >/dev/null 2>&1 && python3 --version
        echo "Install it with your package manager, then run ./setup.sh again:"
        install_hint
        echo "(Older distributions: use the deadsnakes PPA on Ubuntu, or https://www.python.org/downloads/)"
        finish 1
    }
    echo "Creating Python environment with $PY ($("$PY" --version 2>&1))..."
    rm -rf ".venv"
    if ! "$PY" -m venv ".venv" || [ ! -e ".venv/bin/python" ]; then
        rm -rf ".venv"
        echo
        echo "Could not create the Python environment in \"$HERE/.venv\"."
        echo "On Debian / Ubuntu / Mint the venv module is a separate package:"
        echo "  sudo apt install python3-venv     (for another version: python3.12-venv, ...)"
        echo "Then run ./setup.sh again."
        finish 1
    fi
fi
echo "Installing Python packages..."
.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
.venv/bin/python -m pip install --prefer-binary -r requirements.txt ||
    fail "Installing the Python packages failed - see the messages above.
Check the internet connection, then run ./setup.sh again.
(Only 64-bit Linux on x86_64 or aarch64 with glibc 2.28+ is supported; Alpine / musl is not.)"

echo
echo "Setup complete. Start ChainKit with ./ChainKit.sh"
finish 0
