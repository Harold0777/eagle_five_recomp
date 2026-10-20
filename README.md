# Ace Combat 5 — Static Recompilation (Linux Performance Fork)

[![Platform: Linux](https://img.shields.io/badge/platform-Linux-blue)]()
[![Language: C23 / C++17](https://img.shields.io/badge/language-C23%20%2F%20C%2B%2B17-orange)]()
[![Vulkan 1.2+](https://img.shields.io/badge/Vulkan-1.2%2B-red)]()
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)]()
[![CI](https://github.com/Harold0777/eagle_five_recomp/actions/workflows/ci.yml/badge.svg)](https://github.com/Harold0777/eagle_five_recomp/actions/workflows/ci.yml)

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
- **VU1 recompilation** — all VU1 microprograms used by the game are lifted to C
  ahead of time (100% coverage). See [Recent updates](#recent-updates).
- **GS draw state cache** — 256-slot direct-mapped cache; hit rate up from 45% to 88%.
- **EAGLE FIVE launcher (Qt6 / PySide6)** — graphical settings editor with ISO validation,
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
python3 -m ps2recomp /path/to/AC5.iso -o generated

# 2. Configure and build
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

---

## Recent updates

### VU1 recompilation at 100% coverage

All 13 distinct VU1 microprograms the game runs are now lifted to C ahead of
runtime. Previously only 1 of 13 was captured by the census; the other 12 fell
back to the interpreter whenever the native `rn_vp_*` handlers declined a run.

Regenerating the census with `PS2_RN_VP=0` (so the interpreter sees every
microprogram) and running `tools/vurecomp` produced 11 lifted programs
(2 deduplicated) covering 100% of interpreted work:

| CRC | Work share | Note |
|---|---|---|
| `bdb8edb3a90e` | 39.7% | new |
| `32411bda3d49` | 22.4% | previously captured (`3A6610`) |
| `3e3aca578a0d` | 17.5% | new |
| `ca8f017c71da` | 12.5% | new |
| other 7 | ~8% | new |

Result: the run summary now reports `vu1 recompiled: N runs, 0 interpreted (100.0% recompiled)`,
up from 32.3% before.

The generated file `generated/ps2_vu1_progs.inc` is shipped even though
`generated/` is gitignored, because reproducing it requires playing the game
with census mode on. To regenerate it:

```bash
PS2_RN_VP=0 PS2_VU_CENSUS=1 ./build/ac5 ...   # play through the game, then exit
python3 -m tools.vurecomp --programs out/vu_programs -o generated/ps2_vu1_progs.inc
```

### GS draw state cache

The draw state cache was being invalidated by every GS register write that
changed value, including registers `fill_state_compute` never reads. Two
changes:

1. Writes are now filtered to the ~15 registers that actually affect the
   computed state (`gs_reg_affects_state[]`). This cuts invalidations by 84%.
2. The single-slot memo became a 256-slot direct-mapped cache keyed on
   `gs_prim & 0xFF`, so alternating primitive types no longer evict each other.

Result per session:

| Metric | Before | After |
|---|---|---|
| Cache hit rate | 45.2% | 87.7% |
| `fill_state_compute` calls | 7.95M | 0.91M |

FPS is unchanged because `fill_state` was not the bottleneck at 4x internal
resolution — the remaining cost is Vulkan draw submission and GPU fragment
work. Diagnostic counters (`fs_miss_*`) are printed in the run summary to
identify which condition of the memo check fails.

### 3x and 6x removed from the settings menu

The settings menu now only offers Auto, Native, 2x, 4x, 5x, and 8x. See
[Known issues](#known-issues) for the reason.

---

## Benchmarks

All numbers were measured on one machine (Ryzen 7 7735HS, Radeon 680M with RADV, CachyOS, GCC 16.2.1, Release build, hot files at -O3).

### Method

`gsreplay` replays a recorded capture (`out/capture.gscap`, 42 fields) deterministically and checks that every field matches the recorded run. It does not compile the generated guest code, so it measures the runtime (VIF, GIF, GS, texture decode) only.

- Native internal resolution, `PS2_PRESENT_MODE=immediate`, power profile `performance`, lsfg-vk layer disabled.
- Each result is the median ms/field over 10 passes, discarding pass 1.
- Binaries are compared A/B, alternating, in the same session. Run-to-run noise across sessions is about 6%, so only same-session comparisons count.
- A change is accepted only with 0 fidelity divergences and a lower median in 3 consecutive A/B rounds.

### Results

Baseline: about 11.0 ms/field (about 90 fields/s) in `gsreplay`.

| Change | Result | Kept |
|---|---|---|
| PSMT8H texture decode fast path | 0.32 to 0.45 ms/field lower (about 3 to 4%), 3 of 3 rounds, 0 divergences | yes |
| `-march=znver3` | 0.07 to 0.24 ms/field slower | no |
| Global LTO | within noise (-0.01 to +0.09 ms) | no |
| V4-32 UNPACK fast path in the VIF | within noise | no |
| Deferring the epoch bump on identical uploads | not implemented: a diagnostic showed at most 165 of 1449 texture invalidations (11%) could be avoided | no |

### Real game

One 125 s session at internal resolution 2, 1920x1080, present mode immediate: 7464 fields at 59.8 fields/s, 3 fields dropped (all in the first 600), and the EE never waited on a full graphics ring. The graphics thread averaged 3.99 ms/field of the 16.68 ms budget.

Caveats: a single capture and a single session. Gains on other game phases or other hardware may differ.

## Known issues

### 3x internal resolution artifacts

Setting `internal_resolution = 3` (3x) or 6x produces visible artifacts in
volumetric effects (clouds, smoke, contrails). The bug is not present at 2x, 4x,
or 5x.

The cause is still under investigation. The shader math is identical between
3x and 4x for `dtex`, `downsample`, and the `rt_up` block, so the divergence is
likely downstream of the shader — possibly in how RADV handles image tiling for
non-power-of-2 render targets sampled with `VK_SAMPLER_ADDRESS_MODE_REPEAT`.

**Workaround:** use 2x, 4x, or 5x. All work correctly. The 3x and 6x options
have been removed from the settings menu so the bug cannot be selected by
accident, rather than silently promoting 3x to 4x. The `PS2_UPSCALE=3`
environment variable still works if you need it for investigation.

The High preset uses 4x. No fix is currently planned.

## AppImage

O AppImage **não é distribuído**: ele contém o código recompilado do jogo, então cada pessoa gera o seu a partir da própria cópia do jogo.

Requisitos: `generated/` e `ps2_image.bin` já gerados localmente, GCC 15+ ou Clang 13+, SDL3 e Vulkan SDK (`glslc`) instalados, e `python3` com PySide6 ou PyQt no sistema (o launcher usa Qt e o AppImage não embute o Python).

```bash
./tools/make_appimage.sh
./EagleFive-x86_64.AppImage
```

O script compila, empacota o launcher (`tools/ac5_launcher.py`) e copia o `ps2_image.bin` para `~/.local/share/eagle_five/generated/`. Ao abrir o AppImage, o launcher pede a ISO do jogo e inicia o `ac5` com ela. Saves e configurações ficam em `~/.local/share/eagle_five/`. A `libvulkan` vem do sistema, não do AppImage.

