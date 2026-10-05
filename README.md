# Ace Combat 5 — Static Recompilation (Linux Performance Fork)

[![Platform: Linux](https://img.shields.io/badge/platform-Linux-blue)]()
[![Language: C23 / C++17](https://img.shields.io/badge/language-C23%20%2F%20C%2B%2B17-orange)]()
[![Vulkan 1.2+](https://img.shields.io/badge/Vulkan-1.2%2B-red)]()
[![License: MIT](https://img.shields.io/badge/license-MIT-green)]()

A static recompilation of **Ace Combat 5: The Unsung War (USA)** for Linux,
forked from [sal063/Ace-Combat-5-Static-recompilation](https://github.com/sal063/Ace-Combat-5-Static-recompilation)
with a focus on performance, frame pacing, and lower CPU usage.

> ⚠️ **No game files are included.** You need a legally dumped copy of
> Ace Combat 5 (USA) `SLUS_208.51` to use this project.

---

## Fork Improvements

This fork focuses on reducing CPU overhead and improving frame stability
on Linux systems:

- **Bulk GS uploads** — batched Graphics Synthesizer transfers to reduce per-tag overhead.
- **Redundant upload skipping** — identical GS packets are detected and skipped before
  they reach the GPU queue. Cuts ~50% of texture upload bytes in typical scenes.
- **Texture cache cleanup** — tighter VRAM management; fewer cache invalidations.
- **VBlank synchronization** — replaced busy-wait loops with condition variables,
  reducing CPU usage during idle frames and improving frame pacing.
- **EAGLE FIVE launcher (Qt6)** — graphical settings editor with ISO validation,
  preset management, save backup/restore, and integrated console.

---

## Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| **CPU** | x86-64 v2 (SSE4.2) | x86-64 v3 (AVX2) |
| **GPU** | Vulkan 1.2 | Vulkan 1.3+ |
| **RAM** | 4 GB | 8 GB |
| **OS** | Linux (X11 or Wayland) | — |
| **Game** | Ace Combat 5 (USA) `SLUS_208.51` | — |

Build dependencies:

- CMake 3.20+
- GCC 15+ or Clang 13+ (needs `[[gnu::musttail]]` for correct codegen)
- SDL3
- Vulkan SDK (for `glslc`)
- Python 3.10+ (for the recompiler and launcher)
- PySide6 (for the launcher)

---

## Building

```bash
git clone https://github.com/Harold0777/eagle_five_recomp.git
cd eagle_five_recomp

# 1. Recompile the game ISO into C source (one-time, ~30 min)
python -m ps2recomp /path/to/AC5.iso -o generated

# 2. Configure and build
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)


## Known issues

### 3x internal resolution artifacts

Setting `internal_resolution = 3` (3x) produces visible artifacts in volumetric
effects (clouds, smoke, contrails). This is caused by the bicubic sampling path
in `gs.frag` using non-power-of-2 weights (1/3, 2/3) that accumulate rounding
errors across overlapping sprites.

**Workaround:** use 2x or 4x internal resolution. Both work correctly and 4x
provides higher image quality than 3x anyway.

The High preset uses 4x. No fix is currently planned for 3x.
