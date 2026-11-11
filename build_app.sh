#!/bin/sh
# Builds dist/WTFTD.app and dist/WTFTD-<version>-macos.zip: the macOS app (Python and UI; game data comes on first launch).
# Built from a branch other than main, the branch is added to the zip's name: dist/WTFTD-<version>-<branch>-macos.zip.
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }
[ -x .cache/build-venv/bin/python ] || python3 -m venv .cache/build-venv
.cache/build-venv/bin/python -m pip install -q --upgrade pyinstaller pillow  # pillow: .ico -> .icns
.cache/build-venv/bin/python -c "import compression.zstd" 2>/dev/null || {
  echo
  echo "WARNING: this Python has no compression.zstd (it needs 3.14 or newer): the app will not offer to read the installed game."
  echo "To fix it, install Python 3.14 and delete .cache/build-venv."
  echo
}
.cache/build-venv/bin/pyinstaller --noconfirm --clean --windowed --name WTFTD \
  --icon "$PWD/web/favicon.ico" --add-data "$PWD/web:web" --osx-bundle-identifier io.github.stonewarp.wtftd \
  --distpath dist --workpath .cache/build --specpath .cache/build "$PWD/wtftd_app.py"
plist=dist/WTFTD.app/Contents/Info.plist
version=$(python3 -c "import wtftd; print(wtftd.__version__)")
plutil -replace CFBundleShortVersionString -string "$version" "$plist"
plutil -replace LSUIElement -bool YES "$plist"  # no Dock icon of its own: the app window is the browser's
codesign --force --deep --sign - dist/WTFTD.app  # ad hoc signature (Info.plist changed)
name="WTFTD-$version"
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
case "$branch" in ""|main|HEAD) ;; *) name="$name-$(echo "$branch" | tr / -)" ;; esac
rm -f "dist/$name-macos.zip"
ditto -c -k --keepParent dist/WTFTD.app "dist/$name-macos.zip"
echo
echo "Built dist/WTFTD.app and dist/$name-macos.zip"
