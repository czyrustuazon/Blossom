#ifndef PONG_GAME_H
#define PONG_GAME_H

#include <stdbool.h>
#include <stdint.h>

#define GAME_W 400
#define GAME_H 240
#define PADDLE_W 6
#define PADDLE_H 40
#define PADDLE_MARGIN 10
#define BALL_SIZE 6
#define PADDLE_SPEED 4

/* Input bits (main.c maps the 3DS buttons onto these). */
#define IN_P1_UP   (1u << 0)
#define IN_P1_DOWN (1u << 1)
#define IN_P2_UP   (1u << 2)
#define IN_P2_DOWN (1u << 3)

typedef struct {
    int p1_y, p2_y;         /* top edge of each paddle */
    int ball_x, ball_y;     /* top-left of the ball */
    int ball_dx, ball_dy;
    int score1, score2;
} Game;

void game_reset(Game *g);
void game_serve(Game *g, int towards);
void game_update(Game *g, uint32_t input);

#endif
