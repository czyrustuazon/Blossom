/* Recording mock of the libctru NDSP, linear-heap, DSP cache and romfs calls, for host tests. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds/types.h>
#include <3ds/result.h>
#include <3ds/allocator/linear.h>
#include <3ds/services/dsp.h>
#include <3ds/ndsp/ndsp.h>
#include <3ds/ndsp/channel.h>

#include "mock_state.h"

MockState mock;

void mock_fail(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    printf("FAIL: ");
    vprintf(fmt, ap);
    printf("\n");
    va_end(ap);
    mock.failures++;
}

static int next_seq(void) { return ++mock.seq; }

static MockChan *chan(int id, const char *fn)
{
    if (id < 0 || id >= 24) {
        mock_fail("%s: channel %d out of range", fn, id);
        return &mock.chans[0];
    }
    if (!mock.ndsp_up)
        mock_fail("%s(%d) called while NDSP is not initialised", fn, id);
    return &mock.chans[id];
}

/* ---- linear heap ---- */
static void *lin_alloc(size_t size)
{
    if (mock.nlin >= MOCK_MAX_LIN) return NULL;
    void *p = calloc(1, size ? size : 1);
    mock.lin[mock.nlin].p = p;
    mock.lin[mock.nlin].size = size;
    mock.lin[mock.nlin].freed = 0;
    mock.nlin++;
    return p;
}
void *linearAlloc(size_t size) { return lin_alloc(size); }
void *linearMemAlign(size_t size, size_t alignment) { (void)alignment; return lin_alloc(size); }
void *linearRealloc(void *mem, size_t size) { (void)mem; (void)size; return NULL; }
size_t linearGetSize(void *mem)
{
    for (int i = 0; i < mock.nlin; i++)
        if (mock.lin[i].p == mem) return mock.lin[i].size;
    return 0;
}
void linearFree(void *mem)
{
    if (!mem) return;
    for (int i = 0; i < mock.nlin; i++)
        if (mock.lin[i].p == mem && !mock.lin[i].freed) {
            const char *b = mock.lin[i].p;
            if (mock.ndsp_up)
                for (int c = 0; c < 24; c++)
                    for (int q = 0; q < mock.chans[c].nq; q++) {
                        const char *d = mock.chans[c].queue[q]->data_vaddr;
                        if (d >= b && d < b + mock.lin[i].size)
                            mock_fail("linearFree on sample memory still queued on channel %d while NDSP runs", c);
                    }
            mock.lin[i].freed = 1;
            mock.lin[i].freed_seq = next_seq();
            return;
        }
    mock_fail("linearFree on memory that linearAlloc did not return (or freed twice)");
}
u32 linearSpaceFree(void) { return 16u << 20; }

int mock_linear_block(const void *p, size_t len)
{
    for (int i = 0; i < mock.nlin; i++) {
        const char *b = mock.lin[i].p;
        if ((const char *)p >= b && (const char *)p + len <= b + mock.lin[i].size) return i;
    }
    return -1;
}

/* ---- DSP cache ---- */
Result DSP_FlushDataCache(const void *address, u32 size)
{
    if (mock.nflush < MOCK_MAX_FLUSH) {
        mock.flush[mock.nflush].a = address;
        mock.flush[mock.nflush].n = size;
        mock.flush[mock.nflush].seq = next_seq();
        mock.nflush++;
    }
    return 0;
}
Result DSP_InvalidateDataCache(const void *address, u32 size) { (void)address; (void)size; return 0; }

/* ---- romfs + files ---- */
Result romfsMountSelf(const char *name) { (void)name; mock.romfs_mounts++; return 0; }
Result romfsMountFromFile(Handle file, u32 offset, const char *name) { (void)file; (void)offset; (void)name; return 0; }
Result romfsUnmount(const char *name) { (void)name; mock.romfs_mounts--; return 0; }

FILE *mock_fopen(const char *path, const char *mode)
{
    char real[1024];
    const char *root = getenv("MOCK_ROMFS");
    if (strncmp(path, "romfs:/", 7) == 0 && root)
        snprintf(real, sizeof real, "%s/%s", root, path + 7);
    else
        snprintf(real, sizeof real, "%s", path);
    FILE *f = fopen(real, mode);
    if (f) mock.open_files++;
    return f;
}
int mock_fclose(FILE *f)
{
    if (f) mock.open_files--;
    return fclose(f);
}

/* ---- NDSP core ---- */
void ndspUseComponent(const void *binary, u32 size, u16 progMask, u16 dataMask) { (void)binary; (void)size; (void)progMask; (void)dataMask; }
Result ndspInit(void)
{
    mock.init_calls++;
    if (R_SUCCEEDED(mock.init_result)) mock.ndsp_up = 1;
    return mock.init_result;
}
void ndspExit(void)
{
    mock.exit_calls++;
    mock.exit_seq = next_seq();
    if (!mock.ndsp_up) mock_fail("ndspExit called but ndspInit had not succeeded");
    mock.ndsp_up = 0;
}
u32 ndspGetDroppedFrames(void) { return 0; }
u32 ndspGetFrameCount(void) { return 0; }
void ndspSetMasterVol(float volume) { (void)volume; }
float ndspGetMasterVol(void) { return 1.0f; }
void ndspSetOutputMode(ndspOutputMode mode) { (void)mode; }
ndspOutputMode ndspGetOutputMode(void) { return NDSP_OUTPUT_STEREO; }
void ndspSetClippingMode(ndspClippingMode mode) { (void)mode; }
ndspClippingMode ndspGetClippingMode(void) { return NDSP_CLIP_SOFT; }
void ndspSetOutputCount(int count) { (void)count; }
int ndspGetOutputCount(void) { return 1; }
void ndspSetCapture(ndspWaveBuf *capture) { (void)capture; }
void ndspSetCallback(ndspCallback callback, void *data) { (void)callback; (void)data; }
void ndspSurroundSetDepth(u16 depth) { (void)depth; }
u16 ndspSurroundGetDepth(void) { return 0; }
void ndspSurroundSetPos(ndspSpeakerPos pos) { (void)pos; }
ndspSpeakerPos ndspSurroundGetPos(void) { return NDSP_SPKPOS_SQUARE; }
void ndspSurroundSetRearRatio(u16 ratio) { (void)ratio; }
u16 ndspSurroundGetRearRatio(void) { return 0; }
void ndspAuxSetEnable(int id, bool enable) { (void)id; (void)enable; }
bool ndspAuxIsEnabled(int id) { (void)id; return false; }
void ndspAuxSetFrontBypass(int id, bool bypass) { (void)id; (void)bypass; }
bool ndspAuxGetFrontBypass(int id) { (void)id; return false; }
void ndspAuxSetVolume(int id, float volume) { (void)id; (void)volume; }
float ndspAuxGetVolume(int id) { (void)id; return 0; }
void ndspAuxSetCallback(int id, ndspAuxCallback callback, void *data) { (void)id; (void)callback; (void)data; }

/* ---- NDSP channels ---- */
static void clear_queue(MockChan *c)
{
    for (int i = 0; i < c->nq; i++) c->queue[i]->status = NDSP_WBUF_DONE;
    c->nq = 0;
}
void ndspChnReset(int id)
{
    MockChan *c = chan(id, "ndspChnReset");
    clear_queue(c);
    c->format_set = 0;
    c->rate = 0;
    c->clear_seq = next_seq();
}
void ndspChnInitParams(int id) { (void)chan(id, "ndspChnInitParams"); }
bool ndspChnIsPlaying(int id)
{
    MockChan *c = chan(id, "ndspChnIsPlaying");
    return c->nq > 0;
}
u32 ndspChnGetSamplePos(int id) { (void)chan(id, "ndspChnGetSamplePos"); return 0; }
u16 ndspChnGetWaveBufSeq(int id) { (void)chan(id, "ndspChnGetWaveBufSeq"); return 0; }
bool ndspChnIsPaused(int id) { return chan(id, "ndspChnIsPaused")->paused; }
void ndspChnSetPaused(int id, bool paused) { chan(id, "ndspChnSetPaused")->paused = paused; }
void ndspChnSetFormat(int id, u16 format) { MockChan *c = chan(id, "ndspChnSetFormat"); c->format = format; c->format_set = 1; }
u16 ndspChnGetFormat(int id) { return (u16)chan(id, "ndspChnGetFormat")->format; }
void ndspChnSetInterp(int id, ndspInterpType type) { (void)type; (void)chan(id, "ndspChnSetInterp"); }
ndspInterpType ndspChnGetInterp(int id) { (void)chan(id, "ndspChnGetInterp"); return NDSP_INTERP_LINEAR; }
void ndspChnSetRate(int id, float rate) { chan(id, "ndspChnSetRate")->rate = rate; }
float ndspChnGetRate(int id) { return chan(id, "ndspChnGetRate")->rate; }
void ndspChnSetMix(int id, float mix[12]) { (void)mix; (void)chan(id, "ndspChnSetMix"); }
void ndspChnGetMix(int id, float mix[12]) { (void)chan(id, "ndspChnGetMix"); memset(mix, 0, 12 * sizeof(float)); }
void ndspChnSetAdpcmCoefs(int id, u16 coefs[16]) { (void)coefs; (void)chan(id, "ndspChnSetAdpcmCoefs"); }
void ndspChnWaveBufClear(int id)
{
    MockChan *c = chan(id, "ndspChnWaveBufClear");
    clear_queue(c);
    c->clear_seq = next_seq();
}
void ndspChnWaveBufAdd(int id, ndspWaveBuf *buf)
{
    MockChan *c = chan(id, "ndspChnWaveBufAdd");
    int accepted = 1;
    /* libctru silently ignores empty buffers and buffers that are still queued/playing. */
    if (!buf || !buf->nsamples || buf->status == NDSP_WBUF_QUEUED || buf->status == NDSP_WBUF_PLAYING)
        accepted = 0;
    for (int i = 0; i < c->nq; i++)
        if (c->queue[i] == buf) accepted = 0;
    if (mock.nadd < MOCK_MAX_ADD) {
        MockAdd *a = &mock.add[mock.nadd++];
        a->chan = id;
        a->buf = buf;
        a->data = buf ? buf->data_vaddr : NULL;
        a->nsamples = buf ? buf->nsamples : 0;
        a->looping = buf ? buf->looping : 0;
        a->format = c->format_set ? c->format : -1;
        a->rate = c->rate;
        a->accepted = accepted;
        a->seq = next_seq();
    }
    if (accepted && c->nq < MOCK_MAX_Q) {
        buf->status = NDSP_WBUF_QUEUED;
        c->queue[c->nq++] = buf;
    }
}
void ndspChnIirMonoSetEnable(int id, bool enable) { (void)id; (void)enable; }
bool ndspChnIirMonoSetParamsCustomFilter(int id, float a0, float a1, float b0) { (void)id; (void)a0; (void)a1; (void)b0; return true; }
bool ndspChnIirMonoSetParamsLowPassFilter(int id, float f0) { (void)id; (void)f0; return true; }
bool ndspChnIirMonoSetParamsHighPassFilter(int id, float f0) { (void)id; (void)f0; return true; }
void ndspChnIirBiquadSetEnable(int id, bool enable) { (void)id; (void)enable; }
bool ndspChnIirBiquadSetParamsCustomFilter(int id, float a0, float a1, float a2, float b0, float b1, float b2) { (void)id; (void)a0; (void)a1; (void)a2; (void)b0; (void)b1; (void)b2; return true; }
bool ndspChnIirBiquadSetParamsLowPassFilter(int id, float f0, float Q) { (void)id; (void)f0; (void)Q; return true; }
bool ndspChnIirBiquadSetParamsHighPassFilter(int id, float f0, float Q) { (void)id; (void)f0; (void)Q; return true; }
bool ndspChnIirBiquadSetParamsBandPassFilter(int id, float f0, float Q) { (void)id; (void)f0; (void)Q; return true; }
bool ndspChnIirBiquadSetParamsNotchFilter(int id, float f0, float Q) { (void)id; (void)f0; (void)Q; return true; }
bool ndspChnIirBiquadSetParamsPeakingEqualizer(int id, float f0, float Q, float gain) { (void)id; (void)f0; (void)Q; (void)gain; return true; }
