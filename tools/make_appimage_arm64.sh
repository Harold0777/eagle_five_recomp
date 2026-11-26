#!/usr/bin/env bash
# Gera EagleFive-aarch64.AppImage num PC x86-64, dentro de um contêiner arm64
# emulado (qemu-user-static + binfmt, Docker). Reaproveita build-arm64/ se existir;
# sem ele, compila tudo sob emulacao (leva mais de uma hora).
#
#   bash tools/make_appimage_arm64.sh            # usa build-arm64/ ja compilado
#   FULL_BUILD=1 bash tools/make_appimage_arm64.sh   # compila do zero no contêiner
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKER=(docker)
docker info >/dev/null 2>&1 || DOCKER=(sudo docker)

SKIP=1
if [ "${FULL_BUILD:-0}" = 1 ]; then SKIP=0; fi
if [ "$SKIP" = 1 ] && [ ! -x "$ROOT/build-arm64/ac5" ]; then
  echo "build-arm64/ac5 nao existe. Compile antes (README, 'ARM64') ou use FULL_BUILD=1."
  exit 1
fi

"${DOCKER[@]}" run --rm --platform linux/arm64 \
  -e HOSTUID="$(id -u)" -e HOSTGID="$(id -g)" \
  -e ARCH=aarch64 -e SKIP_BUILD="$SKIP" -e BUILD_DIR=/src/build-arm64 \
  -v "$ROOT":/src -w /src debian:trixie bash -c '
    set -e
    apt-get update -qq
    apt-get install -y -qq cmake make clang pkg-config libvulkan-dev glslang-tools \
      libsdl3-dev glslc curl file patchelf binutils squashfs-tools >/dev/null
    LD=linuxdeploy-aarch64.AppImage
    if [ ! -x linuxdeploy-root/usr/bin/linuxdeploy ]; then
      [ -f "$LD" ] || curl -fL -o "$LD" \
        "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/$LD"
      chmod +x "$LD"
      rm -rf linuxdeploy-root
      ok=0
      for off in $(grep -obUa hsqs "$LD" | cut -d: -f1); do
        if unsquashfs -o "$off" -d linuxdeploy-root "$LD" >/dev/null 2>&1; then ok=1; break; fi
        rm -rf linuxdeploy-root
      done
      [ "$ok" = 1 ] || { echo "nao consegui extrair o linuxdeploy"; exit 1; }
    fi
    rc=0
    bash tools/make_appimage.sh || rc=$?
    chown -R "$HOSTUID:$HOSTGID" AppDir build-arm64 EagleFive-aarch64.AppImage \
      linuxdeploy-aarch64.AppImage linuxdeploy-root packaging 2>/dev/null || true
    exit $rc'

echo "Gerado: $ROOT/EagleFive-aarch64.AppImage"
echo "Gerado so empacota o build ARM64; ele ainda nao foi executado em ARM64 real."
