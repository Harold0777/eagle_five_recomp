#!/usr/bin/env bash
# Empacota o build para release no GitHub.
#
# Uso: ./tools/package.sh v1.0.0
#
# Gera em dist/:
#   EagleFive-linux-x86_64-v1.0.0.tar.gz
#   EagleFive-linux-x86_64-v1.0.0.tar.gz.sha256
#
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "Uso: $0 vX.Y.Z"
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BUILD="${BUILD_DIR:-$ROOT/build}"
case "$BUILD" in /*) ;; *) BUILD="$ROOT/$BUILD" ;; esac
DIST="$ROOT/dist"
ARCH="${ARCH:-x86_64}"   # x86_64 (padrão) ou aarch64
NAME="EagleFive-linux-$ARCH-$VERSION"
STAGE="$DIST/$NAME"

echo "[+] Versao: $VERSION"
echo "[+] Raiz:   $ROOT"

# --- localizar binario ---
if [ -x "$BUILD/linux/ac5" ]; then
    BIN="$BUILD/linux/ac5"
elif [ -x "$BUILD/ac5" ]; then
    BIN="$BUILD/ac5"
else
    echo "[!] Binario nao encontrado. Corre: cmake --build build"
    exit 1
fi

[ -f "$ROOT/tools/ac5_launcher.py" ] || { echo "[!] Launcher nao encontrado"; exit 1; }

# --- o binario nao pode ser mais antigo que o ultimo commit do runtime ---
if [ -z "${ALLOW_STALE:-}" ] && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    LAST="$(git -C "$ROOT" log -1 --format=%ct -- runtime third_party CMakeLists.txt config)"
    if [ -n "$LAST" ] && [ "$(stat -c %Y "$BIN")" -lt "$LAST" ]; then
        echo "[!] $BIN e mais antigo que o ultimo commit em runtime/ (nao tem o codigo atual)."
        echo "    Recompile (ex.: bash tools/make_appimage.sh e use BUILD_DIR=build-appimage)"
        echo "    ou force com ALLOW_STALE=1."
        exit 1
    fi
fi

# --- o binario precisa ser da arquitetura pedida ---
case "$ARCH" in
    x86_64)  WANT="x86-64" ;;
    aarch64) WANT="ARM aarch64" ;;
    *) echo "[!] ARCH desconhecida: $ARCH (use x86_64 ou aarch64)"; exit 1 ;;
esac
if command -v file >/dev/null 2>&1; then
    file -L "$BIN" | grep -q "$WANT" || { echo "[!] $BIN nao e $ARCH: $(file -L "$BIN")"; exit 1; }
fi

# --- staging ---
rm -rf "$STAGE"
mkdir -p "$STAGE/shaders" "$STAGE/tools" "$STAGE/generated"

# Binario na raiz (find_exe procura aqui)
cp "$BIN" "$STAGE/ac5"
chmod +x "$STAGE/ac5"

# Launcher em tools/ (para ROOT ser calculado corretamente)
cp "$ROOT/tools/ac5_launcher.py" "$STAGE/tools/"
chmod +x "$STAGE/tools/ac5_launcher.py"

# O launcher gera o ps2_image.bin da ISO do usuario: precisa de make_image.py e elf.py
for f in tools/make_image.py tools/ps2recomp/elf.py; do
    [ -f "$ROOT/$f" ] || { echo "[!] $f nao encontrado"; exit 1; }
done
cp "$ROOT/tools/make_image.py" "$STAGE/tools/"
mkdir -p "$STAGE/tools/ps2recomp"
cp "$ROOT/tools/ps2recomp/elf.py" "$STAGE/tools/ps2recomp/"
[ -f "$ROOT/tools/ps2recomp/__init__.py" ] && cp "$ROOT/tools/ps2recomp/__init__.py" "$STAGE/tools/ps2recomp/"

# O runtime le config/game_symbols.txt e config/pac_names.txt
cp -r "$ROOT/config" "$STAGE/config"

# ps2_image.bin e a imagem em memoria do executavel do jogo: NAO vai no pacote.
# O usuario gera a partir da propria ISO (tools/make_image.py ou o launcher).

# Shaders compilados
if [ -d "$BUILD/shaders" ]; then
    cp "$BUILD/shaders"/*.spv "$STAGE/shaders/" 2>/dev/null || true
    echo "[+] Shaders: $(find "$STAGE/shaders" -name '*.spv' | wc -l)"
fi

# Documentacao
for f in README.md LICENSE CHANGELOG.md; do
    [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$STAGE/"
done

# Settings default (para o launcher ter opcoes antes do primeiro arranque)
if [ -f "$ROOT/tools/ac5_settings.default.ini" ]; then
    cp "$ROOT/tools/ac5_settings.default.ini" "$STAGE/ac5_settings.ini"
    echo "[+] Settings default copiado"
fi

# Pipeline keys pre-aquecidos (independente de GPU/driver; nunca incluir .cache)
if [ -f "$ROOT/tools/ac5_pipelines.keys" ]; then
    cp "$ROOT/tools/ac5_pipelines.keys" "$STAGE/ac5_pipelines.keys"
    echo "[+] Pipeline keys copiado"
fi

# Script de arranque
cat > "$STAGE/run.sh" <<'EOF2'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec python3 tools/ac5_launcher.py "$@"
EOF2
chmod +x "$STAGE/run.sh"

# Arquiteturas fora do x86-64 sao experimentais
if [ "$ARCH" != "x86_64" ]; then
    cat > "$STAGE/EXPERIMENTAL.txt" <<'EOF3'
This ARM64 build is experimental.
- Built with clang for aarch64; not tested on ARM64 hardware or with a GPU.
- The hook layer is x86-64 only: render taps, the sun flare fix and hook-based mods are disabled.
- VU1 uses a scalar path (no SIMD).
- Needs SDL3, Vulkan and (for the launcher) Python 3 with PySide6.
EOF3
fi

# --- trava: nada derivado do jogo pode ir no pacote ---
if find "$STAGE" \( -iname 'ps2_image*' -o -iname 'SLUS_*' -o -iname '*.iso' \) | grep -q .; then
    echo "[!] O pacote contem arquivos derivados do jogo. Abortando."
    exit 1
fi

# --- gerar tar + sha256 ---
cd "$DIST"
tar -czf "$NAME.tar.gz" "$NAME"
sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256"

echo ""
echo "[OK] Pacote criado:"
echo "     dist/$NAME.tar.gz ($(du -h "$NAME.tar.gz" | cut -f1))"
echo "     dist/$NAME.tar.gz.sha256"
