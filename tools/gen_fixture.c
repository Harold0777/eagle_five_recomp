#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "ps2_capture.h"
#include "ps2_runtime.h"

int main(int argc, char **argv) {
    const char *out_path = argc > 1 ? argv[1] : "tests/fixtures/empty.gscap";
    FILE *f = fopen(out_path, "wb");
    if (!f) { perror("fopen"); return 1; }

    ps2_cap_hdr hdr;
    memset(&hdr, 0, sizeof(hdr));
    memcpy(hdr.magic, PS2_CAP_MAGIC, 6);
    hdr.version = PS2_CAP_VERSION;
    hdr.level = 0; // GS level
    hdr.gs_state_size = sizeof(ps2_gs_capstate);
    hdr.vu_state_size = sizeof(ps2_vu_capstate);
    hdr.gif_state_size = sizeof(ps2_gif_capstate);
    
    hdr.vram_size = 4 * 1024 * 1024;
    hdr.spr_size = PS2_SPR_SIZE;
    hdr.vu1_mem_size = PS2_VU1_MEM_SIZE;
    hdr.vu1_micro_size = PS2_VU1_MICRO_SIZE;
    hdr.vu0_mem_size = PS2_VU0_MEM_SIZE;
    hdr.vu0_micro_size = PS2_VU0_MICRO_SIZE;
    
    hdr.nblk = 0;
    hdr.nfields = 1;
    hdr.nrec = 0;
    fwrite(&hdr, sizeof(hdr), 1, f);

    // 1. Estados iniciais
    ps2_gs_capstate gst;
    ps2_vu_capstate vst;
    ps2_gif_capstate fst;
    memset(&gst, 0, sizeof(gst));
    memset(&vst, 0, sizeof(vst));
    memset(&fst, 0, sizeof(fst));
    
    fwrite(&gst, sizeof(gst), 1, f);
    fwrite(&vst, sizeof(vst), 1, f);

    // 2. Memórias do VU
    char zero[4096] = {0};
    for (uint32_t i = 0; i < hdr.vu1_mem_size; i += 4096) fwrite(zero, 4096, 1, f);
    for (uint32_t i = 0; i < hdr.vu1_micro_size; i += 4096) fwrite(zero, 4096, 1, f);
    for (uint32_t i = 0; i < hdr.vu0_mem_size; i += 4096) fwrite(zero, 4096, 1, f);
    for (uint32_t i = 0; i < hdr.vu0_micro_size; i += 4096) fwrite(zero, 4096, 1, f);

    // 3. Estado do GIF
    fwrite(&fst, sizeof(fst), 1, f);

    // 4. VRAM e SPR
    for (uint32_t i = 0; i < hdr.vram_size; i += 4096) fwrite(zero, 4096, 1, f);
    for (uint32_t i = 0; i < hdr.spr_size; i += 4096) fwrite(zero, 4096, 1, f);

    fclose(f);
    printf("Generated %s\n", out_path);
    return 0;
}
