# Changelog

All notable changes to EagleFive (the Linux recompilation of Ace Combat 5: The Unsung War)
are listed here, newest first. Versions follow the release tags.

## Unreleased

### Fixed
- A refused mod patch no longer turns off the lower-priority patches it overlaps. The result
  used to depend on load order; the refusal is now decided before any patch is taken off.
  Thanks to Felipe Marquezini ([@marquezinii](https://github.com/marquezinii)), #1.

### Packaging
- The ARM64 AppImage build extracts `linuxdeploy` inside the container; the README lists the
  ARM64 AppImage.

## v0.3.7 - 2026-11-26

### Fixed
- Tarball: the launcher can now build `ps2_image.bin` from your ISO. The tarball ships
  `tools/make_image.py`, `tools/ps2recomp/elf.py` and `config/`, which were missing in v0.3.6
  (the launcher failed with `No module named 'make_image'`).

### Added
- `EagleFive-aarch64.AppImage`, built in an emulated arm64 container. The ARM64 builds
  (AppImage and tarball) compile and package, but have not been run on ARM64 hardware.

### Changed
- All release files are named `EagleFive...` (tarballs: `EagleFive-linux-<arch>-<version>.tar.gz`).
- `tools/make_appimage.sh` accepts `ARCH`, `BUILD_DIR` and `SKIP_BUILD`.
- `tools/package.sh` refuses a binary older than the last runtime commit and never packages
  `ps2_image.bin`, the ISO or `SLUS_208.51`.

## v0.3.6 - 2026-11-16

### Added
- Experimental ARM64 tarball (clang). `package.sh` accepts `ARCH` and `BUILD_DIR`.
- CI: clang and ARM64 jobs, tests that need no game data, a `gsreplay` smoke test, and the VU
  and VIF self-tests exposed in `gsreplay`.

### Fixed
- Video: an empty bounding box is no longer clamped to the screen edge (signed comparison).

### Documentation
- "Testing and CI" section in the README.
- Native `.so` mods on Linux are documented in `mods/README.md`.

## v0.3.5 - 2026-11-15

### Added
- Launcher: Portuguese settings UI, and an input mapping editor with a controller layout, key
  capture and live gamepad capture through SDL3.
- AppImage keeps settings, config and saves in `~/.local/share/eagle_five`.

### Changed
- Merged upstream (sal063/Ace-Combat-5-Static-recompilation) up to `625ac19`: spin detection on
  `INTC_STAT` reads (`PS2_VSYNC_SLEEP=0` turns it off), Clang dispatch path, x86-64 hooks and
  native `.so` mods on Linux, sRGB swapchain format. In an A/B on the maintainer's machine the
  merge showed no CPU gain or loss.
- README: the recompiler takes the game executable (`SLUS_208.51`), not the ISO, and runs in about
  20 seconds.

### Known limitations
- Native `.so` mods and x86-64 hooks were not tested on Linux in this release.

## v0.3.0 and earlier

See the [releases page](https://github.com/Harold0777/eagle_five_recomp/releases).
