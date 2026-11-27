#ifndef RENDER_H
#define RENDER_H

#include "game.h"

/* Call after gfxInitDefault(). */
void render_init(void);
/* Draws one frame of the game (top screen) and the help (bottom screen). */
void render_frame(const Game *g);
/* Call before gfxExit(). */
void render_exit(void);

#endif
