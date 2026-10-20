#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build-appimage"
APPDIR="$ROOT/AppDir"
LINUXDEPLOY="$ROOT/linuxdeploy-x86_64.AppImage"

cmake -S "$ROOT" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
cmake --build "$BUILD" -j"$(nproc)"

rm -rf "$APPDIR"
DESTDIR="$APPDIR" cmake --install "$BUILD"

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

cd "$DATA"
export AC5_BIN="$HERE/usr/bin/ac5"
exec python3 "$HERE/usr/share/eagle_five/tools/ac5_launcher.py" "$@"
EOF
chmod +x "$ROOT/packaging/AppRun"

if [ ! -x "$LINUXDEPLOY" ]; then
  curl -L -o "$LINUXDEPLOY" \
    https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
  chmod +x "$LINUXDEPLOY"
fi

cd "$ROOT"
export OUTPUT="EagleFive-x86_64.AppImage"
"$LINUXDEPLOY" --appimage-extract-and-run \
  --appdir "$APPDIR" \
  --exclude-library "libvulkan*" \
  --executable "$APPDIR/usr/bin/ac5" \
  --desktop-file "$ROOT/packaging/eagle_five.desktop" \
  --icon-file "$ROOT/packaging/eagle_five.png" \
  --custom-apprun "$ROOT/packaging/AppRun" \
  --output appimage

echo "Gerado: $ROOT/$OUTPUT"
