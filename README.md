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
  reducing CPU usage during idle frames and improving frame pacing. Reads of `INTC_STAT`
  that spin on the vblank bit also sleep until the next vblank (merged from upstream).
  Set `PS2_VSYNC_SLEEP=0` to turn that spin detection off.
- **VU1 recompilation** — all VU1 microprograms used by the game are lifted to C
  ahead of time (100% coverage). See [Recent updates](#recent-updates).
- **GS draw state cache** — 256-slot direct-mapped cache; hit rate up from 45% to 88%.
- **EAGLE FIVE launcher (Qt6 / PySide6)** — graphical settings editor with ISO validation,
  preset management, keyboard and gamepad mapping editor (live gamepad capture through
  SDL3), save backup/restore, and integrated console. The launcher UI is in Portuguese.

---

## Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| **CPU** | x86-64 v2 (SSE4.2) | x86-64 v3 (AVX2) |
| **GPU** | Vulkan 1.2 | Vulkan 1.3+ |
| **RAM** | 3 GB | 6 GB |
| **OS** | Linux (X11 or Wayland) | — |
| **Game** | Ace Combat 5 (USA) `SLUS_208.51` | — |

Build dependencies:

- CMake 3.20+
- GCC 15+ or Clang 13+ (needs `[[gnu::musttail]]` for correct codegen)
- SDL3
- Vulkan SDK (for `glslc`)
- Python 3.10+ (for the recompiler and launcher)
- PySide6 (for the launcher)
- `bsdtar` (libarchive) or `7z` (p7zip), to extract the game executable from the ISO

On Arch / CachyOS:

```bash
sudo pacman -S --needed base-devel cmake sdl3 vulkan-headers vulkan-icd-loader shaderc libarchive python
```

---

## Building

```bash
git clone https://github.com/Harold0777/eagle_five_recomp.git
cd eagle_five_recomp

# 1. Extract the game executable from your ISO
bsdtar -xf /path/to/AC5.iso SLUS_208.51      # or: 7z e /path/to/AC5.iso SLUS_208.51

# 2. Recompile it into C source (one-time, about 20 seconds)
PYTHONPATH=tools python3 -m ps2recomp SLUS_208.51 -o generated \
  --ida-db config/ida_db.json --ida-seeds config/ida_seeds.json \
  --symbols config/sdk_symbols.json --symbols config/manual_symbols.json \
  --overrides config/overrides.json --hooks config/hooks.json \
  --report /tmp/report.json

# 3. Configure and build
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

The recompiler takes the game executable (`SLUS_208.51`), not the ISO. When it
finishes it should report 10742 functions in 43 files with 98.04% of `.text`
covered, the same numbers as `config/report.json`. If yours differ, something is
wrong with the inputs.

The generated sources are derived from the game, so `generated/` is gitignored
(except `ps2_vu1_progs.inc`). Never commit it, the ISO or `SLUS_208.51`.

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

### Upstream merge A/B

Measured on a different machine (Xeon E5-2690 v4, Radeon RX 7600, CachyOS, GCC 16.2.1): the build
with upstream `625ac19` merged against the previous `main`, two alternating 120 s rounds of the game's
opening sequence with no input.

- Both builds ran at 59.9 fields/s with 2 to 4 dropped fields, using about 51% CPU summed over all
  threads. The EE practically never waited on the graphics ring, so this machine is not CPU-bound.
- The merge costs about +0.35 s of system time per run, consistently.
- `PS2_VSYNC_SLEEP=0` changes nothing here: the fork already waits on a condition variable in
  `ps2_kernel_poll_vblank` (up to 2 ms when no vblank is pending), so the upstream wait is redundant.

The merge is about Linux hooks, native `.so` mods and a more robust swapchain, not speed.

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

## Downloads and AppImage

The [latest release page](https://github.com/Harold0777/eagle_five_recomp/releases/latest) has:

- `EagleFive-x86_64.AppImage` (with a `.sha256` file): single file with the graphical launcher (`tools/ac5_launcher.py`).
- `EagleFive-linux-x86_64-<version>.tar.gz` (with a `.sha256` file): portable tarball.
- `EagleFive-aarch64.AppImage` (with a `.sha256` file): **experimental** ARM64 AppImage, see below.
- `EagleFive-linux-aarch64-<version>.tar.gz` (with a `.sha256` file): **experimental** ARM64 tarball, see below.

None of them includes the game. You need your own legally dumped ISO of Ace Combat 5 (USA, `SLUS_208.51`).

### Running the AppImage

```bash
chmod +x EagleFive-x86_64.AppImage
./EagleFive-x86_64.AppImage
```

Pick your ISO in the launcher and press play. On the first run the launcher extracts the game executable from the ISO and creates `ps2_image.bin` in `~/.local/share/eagle_five/generated/`. Saves and settings also live in `~/.local/share/eagle_five/`.

Requirements: `python3` with PySide6 or PyQt (the launcher uses Qt and the AppImage does not bundle Python) and a Vulkan driver. The system `libvulkan` is used, not a bundled one.

### Running the tarball

The tarball does not include `ps2_image.bin`. Create it once from your ISO with the helper script in this repository, then run `ac5` from the extracted folder:

```bash
git clone https://github.com/Harold0777/eagle_five_recomp
python3 eagle_five_recomp/tools/make_image.py /path/to/AC5.iso generated
./ac5 --data generated --disc /path/to/AC5.iso
```

### ARM64 (experimental)

The ARM64 tarball is built with clang and has **not been run on ARM64 hardware or with a GPU**. Under
emulation (qemu-user), `ac5 --hle-test`, `ac5 --spu2-test` and `ac5 --selftest` pass. The hook layer is
x86-64 only, so on ARM64 render taps, the sun flare fix and hook-based mods are disabled, and VU1 runs a
scalar path. Create `ps2_image.bin` the same way as for the x86-64 tarball.

### Building the AppImage yourself

Needs the generated sources (`generated/`), GCC 15+ or Clang 13+, SDL3 and the Vulkan SDK (`glslc`):

```bash
./tools/make_appimage.sh
```


## Testing and CI

The project has self-tests that run without a game disc or capture.

### Built-in self-tests

`gsreplay` can run self-tests for the VU (vector unit) and the VIF (VPU interface):

```bash
./build/gsreplay --vu-test
./build/gsreplay --vif-test
```

They check the flag pipeline, Q/P register latency and unpacking logic, exit with 0 on success and 1 on
failure, and print the failing check. On x86-64 they exercise the SIMD path, on ARM64 the scalar fallback
(see `VU_SIMD` in `ps2_vu.c`).

The game binary has its own tests. These two need no game data:

```bash
./build/ac5 --hle-test --novideo
./build/ac5 --spu2-test --novideo
```

`./build/ac5 --selftest --data generated --disc /path/to/AC5.iso --novideo` checks the file layer
against your disc, so it needs `generated/ps2_image.bin` and the ISO.

### Smoke test script

`tools/smoke.sh` is the script the CI runs. It checks that:

- the binary is a valid ELF for the current architecture and resolves its shared libraries;
- `--help` reaches the argument parser;
- `--novideo` gets past VU initialization without a SIGILL (important on ARM64);
- the VU and VIF self-tests pass.

Run it locally with a populated build directory:

```bash
bash tools/smoke.sh
```

### CI

`.github/workflows/ci.yml` runs on pushes to `main` and on pull requests, on:

- linux (gcc 15, x86-64)
- linux (clang, x86-64)
- linux (clang, arm64)

Each job builds `gsreplay` with `-DPS2_RUNTIME_ONLY=ON`, runs the smoke test and
`tools/test_patch.py` / `tools/test_settings.py`. CI cannot build the game itself or the AppImage,
because they need `generated/`, which is derived from the game. The `gsreplay binaries` workflow
builds `gsreplay` for x86-64 and ARM64 on `v*` tags. Playable releases are built locally with
`tools/make_appimage.sh` and `tools/package.sh`.

## Credits

- Original static recompilation: [sal063/Ace-Combat-5-Static-recompilation](https://github.com/sal063/Ace-Combat-5-Static-recompilation).
  This fork has merged upstream up to commit `625ac19` ("Performence overhaul": INTC_STAT spin
  detection, Clang dispatch path, Linux hooks and native `.so` mods, sRGB swapchain format).
- Ace Combat 5: The Unsung War is a trademark and work of Bandai Namco. This project contains
  no game data and requires your own legally dumped copy.
