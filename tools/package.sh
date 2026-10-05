#!/usr/bin/env bash
# Empacota o build para release no GitHub.
#
# Uso: ./tools/package.sh v1.0.0
#
# Gera em dist/:
#   ac5-recomp-linux-x86_64-v1.0.0.tar.gz
#   ac5-recomp-linux-x86_64-v1.0.0.tar.gz.sha256
#
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    echo "Uso: $0 vX.Y.Z"
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BUILD="$ROOT/build"
DIST="$ROOT/dist"
NAME="ac5-recomp-linux-x86_64-$VERSION"
STAGE="$DIST/$NAME"

echo "[+] Versao: $VERSION"
echo "[+] Raiz:   $ROOT"

# --- localizar binario (aceita build/linux/ac5 ou build/ac5) ---
if [ -x "$BUILD/linux/ac5" ]; then
    BIN="$BUILD/linux/ac5"
elif [ -x "$BUILD/ac5" ]; then
    BIN="$BUILD/ac5"
else
    echo "[!] Binario nao encontrado. Corre: cmake --build build"
    exit 1
fi

[ -f "$ROOT/tools/ac5_launcher.py" ] || { echo "[!] Launcher nao encontrado"; exit 1; }

# --- staging ---
rm -rf "$STAGE"
mkdir -p "$STAGE/shaders"

# --- binario + launcher ---
cp "$BIN" "$STAGE/ac5"
cp "$ROOT/tools/ac5_launcher.py" "$STAGE/"
chmod +x "$STAGE/ac5" "$STAGE/ac5_launcher.py"

# --- shaders compilados ---
SHADERS_SRC="$BUILD/shaders"
if [ -d "$SHADERS_SRC" ]; then
    cp "$SHADERS_SRC"/*.spv "$STAGE/shaders/" 2>/dev/null || true
    echo "[+] Shaders: $(find "$STAGE/shaders" -name '*.spv' | wc -l) ficheiros"
fi

# --- documentacao ---
for f in README.md LICENSE CHANGELOG.md; do
    [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$STAGE/"
done

# --- script de arranque ---
cat > "$STAGE/run.sh" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec python3 ac5_launcher.py "$@"
EOF
chmod +x "$STAGE/run.sh"

# --- gerar tar + sha256 ---
cd "$DIST"
tar -czf "$NAME.tar.gz" "$NAME"
sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256"

echo ""
echo "[OK] Pacote criado:"
echo "     dist/$NAME.tar.gz ($(du -h "$NAME.tar.gz" | cut -f1))"
echo "     dist/$NAME.tar.gz.sha256"
