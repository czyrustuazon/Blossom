/* Runs src/sound.c against the recording NDSP mock. Prints FAIL: lines, then DONE. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds/types.h>
#include <3ds/ndsp/ndsp.h>
#include <3ds/ndsp/channel.h>

#include "mock_state.h"
#include "sound.h"

static unsigned char *read_file(const char *name, long *len)
{
    char path[1024];
    snprintf(path, sizeof path, "%s/sfx/%s", getenv("MOCK_ROMFS"), name);
    FILE *f = fopen(path, "rb");
    if (!f) { printf("FAIL: driver cannot read %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END);
    *len = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *buf = malloc(*len);
    if (fread(buf, 1, *len, f) != (size_t)*len) exit(2);
    fclose(f);
    return buf;
}

static int last_accepted_since(int from)
{
    int found = -1;
    for (int i = from; i < mock.nadd; i++)
        if (mock.add[i].accepted) found = i;
    return found;
}

static int flushed(const void *data, size_t len, int before_seq)
{
    for (int i = 0; i < mock.nflush; i++) {
        const char *a = mock.flush[i].a;
        if (mock.flush[i].seq < before_seq && a <= (const char *)data &&
            a + mock.flush[i].n >= (const char *)data + len)
            return 1;
    }
    return 0;
}

static int check_play(const char *what, const unsigned char *pcm, long len, int from)
{
    int i = last_accepted_since(from);
    if (i < 0) {
        if (mock.nadd > from)
            mock_fail("%s: ndspChnWaveBufAdd was called but libctru would ignore it (empty buffer, or one that is still queued/playing)", what);
        else
            mock_fail("%s: nothing was queued with ndspChnWaveBufAdd", what);
        return -1;
    }
    MockAdd *a = &mock.add[i];
    if (a->nsamples != (unsigned)(len / 2))
        mock_fail("%s: nsamples is %u, the effect has %ld PCM16 samples (%ld bytes)", what, a->nsamples, len / 2, len);
    if (a->looping)
        mock_fail("%s: buffer is looping", what);
    if (a->format != -1 && a->format != NDSP_FORMAT_MONO_PCM16)
        mock_fail("%s: channel format is 0x%x, the effects are mono PCM16", what, a->format);
    if (a->rate < 22049.0f || a->rate > 22051.0f)
        mock_fail("%s: channel rate is %.1f, the effects are 22050 Hz", what, a->rate);
    if (!a->data || mock_linear_block(a->data, (size_t)len) < 0) {
        mock_fail("%s: sample data is not in linear memory (linearAlloc) - the DSP cannot read it", what);
        return a->chan;
    }
    if (memcmp(a->data, pcm, (size_t)len) != 0)
        mock_fail("%s: queued sample data differs from romfs:/sfx file", what);
    if (!flushed(a->data, (size_t)len, a->seq))
        mock_fail("%s: sample data was not flushed to the DSP (DSP_FlushDataCache) before queueing", what);
    return a->chan;
}

static void check_released(void)
{
    for (int i = 0; i < mock.nlin; i++)
        if (!mock.lin[i].freed) mock_fail("linear memory block %d (%zu bytes) was never freed", i, mock.lin[i].size);
    if (mock.open_files != 0)
        mock_fail("%d romfs file(s) left open", mock.open_files);
}

static void scenario_ok(void)
{
    long nb, ns;
    unsigned char *bounce = read_file("bounce.pcm", &nb);
    unsigned char *score = read_file("score.pcm", &ns);
    mock.init_result = 0;
    for (int i = 0; i < 24; i++) mock.chans[i].rate = 0;

    if (!sound_init()) mock_fail("sound_init returned false although NDSP started");
    if (mock.init_calls != 1) mock_fail("ndspInit called %d times", mock.init_calls);

    int mark = mock.nadd;
    sound_play(SFX_BOUNCE);
    int cb = check_play("bounce", bounce, nb, mark);

    mark = mock.nadd;
    sound_play(SFX_SCORE);
    int cs = check_play("score", score, ns, mark);
    if (cb >= 0 && cb == cs)
        mock_fail("bounce and score share channel %d: one cuts the other off", cb);

    /* Bounce is still playing (queued in the mock): playing it again must restart it. */
    int first = last_accepted_since(0);
    (void)first;
    mark = mock.nadd;
    int clear_before = cb >= 0 ? mock.chans[cb].clear_seq : 0;
    sound_play(SFX_BOUNCE);
    int again = last_accepted_since(mark);
    if (again < 0) {
        mock_fail("playing bounce again while it plays queues nothing libctru would accept: it never restarts");
    } else {
        if (mock.add[again].chan != cb)
            mock_fail("bounce moved from channel %d to %d", cb, mock.add[again].chan);
        if (cb >= 0 && mock.chans[cb].clear_seq == clear_before)
            mock_fail("bounce was queued behind itself instead of restarting (channel not cleared)");
        if (mock.chans[cb].nq != 1)
            mock_fail("bounce channel has %d buffers queued after the restart", mock.chans[cb].nq);
        check_play("bounce again", bounce, nb, mark);
    }

    sound_exit();
    if (mock.exit_calls != 1) mock_fail("ndspExit called %d times", mock.exit_calls);
    check_released();
    free(bounce);
    free(score);
}

static void scenario_nofirm(void)
{
    mock.init_result = (long)0xD880A7FA; /* no sdmc:/3ds/dspfirm.cdc */
    if (sound_init()) mock_fail("sound_init returned true although ndspInit failed");
    sound_play(SFX_BOUNCE);
    sound_play(SFX_SCORE);
    if (mock.nadd) mock_fail("sounds were queued although NDSP is not running");
    sound_exit();
    if (mock.exit_calls) mock_fail("ndspExit called although ndspInit failed");
    check_released();
}

int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc > 1 && strcmp(argv[1], "nofirm") == 0)
        scenario_nofirm();
    else
        scenario_ok();
    printf("DONE failures=%d\n", mock.failures);
    return 0;
}
