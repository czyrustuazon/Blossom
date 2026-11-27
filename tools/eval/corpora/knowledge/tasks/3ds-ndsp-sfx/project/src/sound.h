#ifndef SOUND_H
#define SOUND_H

#include <stdbool.h>

typedef enum {
    SFX_BOUNCE, /* romfs:/sfx/bounce.pcm */
    SFX_SCORE,  /* romfs:/sfx/score.pcm */
    SFX_COUNT
} Sfx;

/* Call after romfsInit(). Returns false when sound is unavailable; the game then runs muted. */
bool sound_init(void);
/* Starts an effect. */
void sound_play(Sfx sfx);
/* Call before romfsExit(). */
void sound_exit(void);

#endif
