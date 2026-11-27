#ifndef MOCK_STATE_H
#define MOCK_STATE_H

#include <stddef.h>

#define MOCK_MAX_LIN 64
#define MOCK_MAX_FLUSH 256
#define MOCK_MAX_ADD 64
#define MOCK_MAX_Q 16

typedef struct { void *p; size_t size; int freed; int freed_seq; } MockLin;
typedef struct { const void *a; unsigned n; int seq; } MockFlush;
typedef struct {
    int chan; void *buf; const void *data; unsigned nsamples; int looping;
    int format; float rate; int accepted; int seq;
} MockAdd;
typedef struct {
    int format, format_set; float rate; int paused; int clear_seq;
    struct tag_ndspWaveBuf *queue[MOCK_MAX_Q]; int nq;
} MockChan;

typedef struct {
    int seq, failures;
    long init_result;
    int ndsp_up, init_calls, exit_calls, exit_seq;
    int romfs_mounts, open_files;
    MockLin lin[MOCK_MAX_LIN]; int nlin;
    MockFlush flush[MOCK_MAX_FLUSH]; int nflush;
    MockAdd add[MOCK_MAX_ADD]; int nadd;
    MockChan chans[24];
} MockState;

extern MockState mock;
void mock_fail(const char *fmt, ...);
int mock_linear_block(const void *p, size_t len);

#endif
