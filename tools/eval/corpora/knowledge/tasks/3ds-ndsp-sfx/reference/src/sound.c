#include <3ds.h>
#include <stdio.h>
#include <string.h>

#include "sound.h"

#define SFX_RATE 22050.0f

typedef struct {
    s16 *data;      /* linear memory: the DSP reads it directly */
    u32 bytes;
    ndspWaveBuf wave;
} Effect;

static const char *const paths[SFX_COUNT] = {
    [SFX_BOUNCE] = "romfs:/sfx/bounce.pcm",
    [SFX_SCORE] = "romfs:/sfx/score.pcm",
};

static Effect effects[SFX_COUNT];
static bool ready;

static bool load(Effect *e, const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return false;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    bool ok = size > 0;
    if (ok) {
        e->data = linearAlloc((size_t)size);
        ok = e->data && fread(e->data, 1, (size_t)size, f) == (size_t)size;
    }
    fclose(f);
    if (!ok)
        return false;
    e->bytes = (u32)size;
    DSP_FlushDataCache(e->data, e->bytes);
    memset(&e->wave, 0, sizeof e->wave);
    e->wave.data_vaddr = e->data;
    e->wave.nsamples = e->bytes / sizeof(s16);
    e->wave.looping = false;
    e->wave.status = NDSP_WBUF_FREE;
    return true;
}

static void free_effects(void)
{
    for (int i = 0; i < SFX_COUNT; i++) {
        linearFree(effects[i].data);
        effects[i].data = NULL;
    }
}

bool sound_init(void)
{
    /* Fails when the DSP firmware (sdmc:/3ds/dspfirm.cdc) has not been dumped. */
    if (R_FAILED(ndspInit()))
        return false;

    for (int i = 0; i < SFX_COUNT; i++) {
        if (!load(&effects[i], paths[i])) {
            free_effects();
            ndspExit();
            return false;
        }
    }

    ndspSetOutputMode(NDSP_OUTPUT_STEREO);
    for (int ch = 0; ch < SFX_COUNT; ch++) { /* one channel per effect */
        ndspChnReset(ch);
        ndspChnSetInterp(ch, NDSP_INTERP_LINEAR);
        ndspChnSetRate(ch, SFX_RATE);
        ndspChnSetFormat(ch, NDSP_FORMAT_MONO_PCM16);
    }
    ready = true;
    return true;
}

void sound_play(Sfx sfx)
{
    if (!ready || (unsigned)sfx >= SFX_COUNT)
        return;
    const int ch = (int)sfx;
    ndspChnWaveBufClear(ch); /* restart if it is still playing */
    effects[sfx].wave.status = NDSP_WBUF_FREE;
    ndspChnWaveBufAdd(ch, &effects[sfx].wave);
}

void sound_exit(void)
{
    if (!ready)
        return;
    for (int ch = 0; ch < SFX_COUNT; ch++)
        ndspChnWaveBufClear(ch);
    ndspExit();
    free_effects();
    ready = false;
}
