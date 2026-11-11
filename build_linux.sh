#!/bin/sh
# Builds dist/WTFTD and dist/WTFTD-<version>-linux.tar.gz: the Linux app, one file (Python and UI; game data comes on first launch).
# Built from a branch other than main, the branch is added to the name: dist/WTFTD-<version>-<branch>-linux.tar.gz.
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
[ -x .cache/build-venv/bin/python ] || python3 -m venv .cache/build-venv
.cache/build-venv/bin/python -m pip install -q --upgrade pyinstaller
.cache/build-venv/bin/python -c "import compression.zstd" 2>/dev/null || {
  echo
  echo "WARNING: this Python has no compression.zstd (it needs 3.14 or newer): the app will not offer to read the installed game."
  echo "To fix it, install Python 3.14 and delete .cache/build-venv."
  echo
}
.cache/build-venv/bin/pyinstaller --noconfirm --clean --onefile --name WTFTD --add-data "$PWD/web:web" \
  --distpath dist --workpath .cache/build --specpath .cache/build "$PWD/wtftd_app.py"
name="WTFTD-$(python3 -c "import wtftd; print(wtftd.__version__)")"
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
case "$branch" in ""|main|HEAD) ;; *) name="$name-$(echo "$branch" | tr / -)" ;; esac
tar -czf "dist/$name-linux.tar.gz" -C dist WTFTD  # a tar keeps the file executable, a zip would not
echo
echo "Built dist/WTFTD and dist/$name-linux.tar.gz"
