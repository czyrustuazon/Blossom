/* Host-side stand-in for <3ds.h>: the real libctru types and NDSP/linear/romfs declarations,
   implemented by the recording mock in mock_ndsp.c. romfs:/ paths are served from MOCK_ROMFS. */
#ifndef MOCK_3DS_H
#define MOCK_3DS_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds/types.h>
#include <3ds/result.h>
#include <3ds/allocator/linear.h>
#include <3ds/services/dsp.h>
#include <3ds/ndsp/ndsp.h>
#include <3ds/ndsp/channel.h>
#include <3ds/romfs.h>

FILE *mock_fopen(const char *path, const char *mode);
int mock_fclose(FILE *f);
#define fopen mock_fopen
#define fclose mock_fclose

#endif
