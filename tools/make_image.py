#!/usr/bin/env python3
"""Build ps2_image.bin (the in-memory image of the game's ELF) from the game ISO.

Usage: make_image.py <AC5.iso | SLUS_208.51> <outdir>
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

SECTOR = 2048
ELF_NAME = "SLUS_208.51"


def _load_elf_module():
    path = Path(__file__).resolve().parent / "ps2recomp" / "elf.py"
    spec = importlib.util.spec_from_file_location("ps2recomp_elf", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


def read_iso_file(iso, name):
    with open(iso, "rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        if len(pvd) < SECTOR or pvd[1:6] != b"CD001":
            raise ValueError("not a valid ISO9660 image")
        root = pvd[156:190]
        lba = int.from_bytes(root[2:6], "little")
        size = int.from_bytes(root[10:14], "little")
        if not 0 < size <= 1 << 20:
            raise ValueError("invalid ISO root directory")
        f.seek(lba * SECTOR)
        data = f.read(size)
        off = 0
        while off + 33 <= len(data):
            rec_len = data[off]
            if rec_len == 0:
                off = (off // SECTOR + 1) * SECTOR
                continue
            name_len = data[off + 32]
            n = data[off + 33:off + 33 + name_len].decode("ascii", "replace")
            if n.split(";")[0].upper() == name:
                f_lba = int.from_bytes(data[off + 2:off + 6], "little")
                f_size = int.from_bytes(data[off + 10:off + 14], "little")
                f.seek(f_lba * SECTOR)
                return f.read(f_size)
            off += rec_len
    raise ValueError("%s not found in the ISO root" % name)


def build_image(src, outdir):
    """Write <outdir>/ps2_image.bin from an ISO or a raw ELF. Returns (path, base, size)."""
    src = Path(src)
    with open(src, "rb") as f:
        is_elf = f.read(4) == b"\x7fELF"
    tmp = None
    if is_elf:
        elf_path = str(src)
    else:
        raw = read_iso_file(src, ELF_NAME)
        tmp = tempfile.NamedTemporaryFile(suffix=".elf", delete=False)
        tmp.write(raw)
        tmp.close()
        elf_path = tmp.name
    try:
        base, img = _load_elf_module().ElfFile(elf_path).image()
    finally:
        if tmp:
            os.unlink(tmp.name)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "ps2_image.bin"
    part = outdir / "ps2_image.bin.tmp"
    part.write_bytes(bytes(img))
    os.replace(part, out)
    return out, base, len(img)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    path, base, size = build_image(sys.argv[1], sys.argv[2])
    print("wrote %s (%d bytes, base 0x%08X)" % (path, size, base))
