#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ARCH: x86_64 (default on x86-64 hosts) or aarch64 (default on arm64 hosts).
# BUILD_DIR: build tree to use (default: build-appimage, or build-appimage-aarch64).
# SKIP_BUILD=1: do not configure/compile, only install an existing BUILD_DIR.
ARCH="${ARCH:-$(uname -m)}"
case "$ARCH" in
  x86_64|aarch64) ;;
  arm64) ARCH=aarch64 ;;
  *) echo "ARCH desconhecida: $ARCH (use x86_64 ou aarch64)"; exit 1 ;;
esac
export ARCH
if [ -n "${BUILD_DIR:-}" ]; then BUILD="$BUILD_DIR"
elif [ "$ARCH" = x86_64 ]; then BUILD="$ROOT/build-appimage"
else BUILD="$ROOT/build-appimage-$ARCH"; fi
APPDIR="$ROOT/AppDir"
LINUXDEPLOY="$ROOT/linuxdeploy-$ARCH.AppImage"

if [ "${SKIP_BUILD:-0}" = 1 ]; then
  [ -x "$BUILD/ac5" ] || { echo "SKIP_BUILD=1 mas $BUILD/ac5 nao existe"; exit 1; }
else
  cmake -S "$ROOT" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
  cmake --build "$BUILD" -j"$(nproc)"
fi

rm -rf "$APPDIR"
DESTDIR="$APPDIR" cmake --install "$BUILD" --prefix /usr

install -Dm644 "$ROOT/tools/ac5_settings.default.ini" \
  "$APPDIR/usr/share/eagle_five/ac5_settings.default.ini"

mkdir -p "$ROOT/packaging"

cat > "$ROOT/packaging/eagle_five.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Eagle Five
Comment=Ace Combat 5 - Linux recomp
Exec=ac5
Icon=eagle_five
Categories=Game;
Terminal=false
EOF

cat > "$ROOT/packaging/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PATH="$HERE/usr/bin:$PATH"
export LD_LIBRARY_PATH="$HERE/usr/lib:${LD_LIBRARY_PATH:-}"

DATA="${XDG_DATA_HOME:-$HOME/.local/share}/eagle_five"
mkdir -p "$DATA"
ln -sfn "$HERE/usr/share/eagle_five/shaders" "$DATA/shaders"
[ -d "$DATA/config" ] || cp -r "$HERE/usr/share/eagle_five/config" "$DATA/config"
[ -f "$DATA/ac5_settings.ini" ] || cp "$HERE/usr/share/eagle_five/ac5_settings.default.ini" "$DATA/ac5_settings.ini"

cd "$DATA"
export AC5_BIN="$HERE/usr/bin/ac5"
export PS2_SETTINGS_FILE="$DATA/ac5_settings.ini"
exec python3 "$HERE/usr/share/eagle_five/tools/ac5_launcher.py" "$@"
EOF
chmod +x "$ROOT/packaging/AppRun"

if [ ! -x "$LINUXDEPLOY" ]; then
  curl -L -o "$LINUXDEPLOY" \
    "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-$ARCH.AppImage"
  chmod +x "$LINUXDEPLOY"
fi

cd "$ROOT"
export OUTPUT="EagleFive-$ARCH.AppImage"
LD="$LINUXDEPLOY --appimage-extract-and-run"
if [ -x "$ROOT/linuxdeploy-root/usr/bin/linuxdeploy" ]; then
  LD="$ROOT/linuxdeploy-root/usr/bin/linuxdeploy"
  export PATH="$ROOT/linuxdeploy-root/usr/bin:$PATH"
  export APPIMAGE_EXTRACT_AND_RUN=1
fi
$LD \
  --appdir "$APPDIR" \
  --exclude-library "libvulkan*" \
  --executable "$APPDIR/usr/bin/ac5" \
  --desktop-file "$ROOT/packaging/eagle_five.desktop" \
  --icon-file "$ROOT/packaging/eagle_five.png" \
  --custom-apprun "$ROOT/packaging/AppRun" \
  --output appimage

echo "Gerado: $ROOT/$OUTPUT"
