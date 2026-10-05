#!/usr/bin/env fish
# Restaura o binário pré-compilado que funciona.
# Guarda o backup em ~/ac5-working/ac5-c0b07c-*.

set ROOT (realpath (dirname (status -f))/..)
set SRC (ls ~/ac5-working/ac5-c0b07c-* 2>/dev/null | head -1)
set DST $ROOT/build/linux/ac5

if test -z "$SRC"
    echo "[!] Backup não encontrado em ~/ac5-working/"
    exit 1
end

mkdir -p (dirname $DST)
cp $SRC $DST
chmod +x $DST
echo "[+] Restaurado: $DST"
