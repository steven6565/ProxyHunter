#!/usr/bin/env bash
# Proxy Hunter installer - Linux, Ubuntu, VPS and Termux (Android)
set -eu

cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

echo "==> Proxy Hunter v2.0 installer"
echo "==> Python: $($PY --version 2>&1)"
$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
    echo "ERROR: Python 3.11 or newer is required. Install it with 'pkg install python' (Termux) or your package manager."
    exit 1
}
if ! command -v openssl >/dev/null 2>&1; then
    echo "NOTE: openssl not found. Generate a certificate before enabling TLS on a remote gateway."
fi

# A virtual environment keeps the system Python clean. On Termux this works
# out of the box; if venv is unavailable we fall back to a --user install.
VENV=0
if $PY -m venv .venv >/dev/null 2>&1; then
    VENV=1
    PY=".venv/bin/python"
    echo "==> Using virtual environment: .venv"
    "$PY" -m pip install --disable-pip-version-check --upgrade pip
    "$PY" -m pip install --disable-pip-version-check -r requirements.txt
else
    echo "==> venv unavailable; installing into the user site-packages"
    $PY -m pip install --user --disable-pip-version-check -r requirements.txt
fi

mkdir -p output/protocols output/countries output/filters output/logs data
chmod +x main.py

echo
echo "Install complete. Start with:"
if [ "$VENV" -eq 1 ]; then
    echo "  .venv/bin/python main.py"
else
    echo "  python3 main.py"
fi
