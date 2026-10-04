# Ace Combat 5 - Static Recompilation (Linux Performance Fork)

This is a fork of the [Ace-Combat-5-Static-recompilation](https://github.com/sal063/Ace-Combat-5-Static-recompilation) project, focused on improving performance and stability on Linux systems.

## Improvements in this Fork
* **Bulk GS Uploads:** Reduced overhead by batching Graphics Synthesizer transfers.
* **Redundant Upload Skipping:** Added checks to avoid re-uploading identical GS packets.
* **Texture Cache Cleanup:** Optimized VRAM management.
* **VBlank Synchronization:** Replaced busy-wait loops with condition variables for VBlank, reducing CPU usage and improving frame pacing.

## Disclaimer
**NO GAME FILES ARE INCLUDED.** 
This repository contains only reverse-engineered C/C++ engine code and recompilation wrappers. It does **not** contain the game ISO, any proprietary Sony PS2 BIOS, assets, audio, or any copyrighted Namco material. You must provide your own legally dumped copy of the game.
