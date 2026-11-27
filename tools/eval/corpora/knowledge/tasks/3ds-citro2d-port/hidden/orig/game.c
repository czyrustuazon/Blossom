#include "game.h"

static int clamp(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

void game_serve(Game *g, int towards)
{
    g->ball_x = (GAME_W - BALL_SIZE) / 2;
    g->ball_y = (GAME_H - BALL_SIZE) / 2;
    g->ball_dx = towards < 0 ? -3 : 3;
    g->ball_dy = 2;
}

void game_reset(Game *g)
{
    g->p1_y = g->p2_y = (GAME_H - PADDLE_H) / 2;
    g->score1 = g->score2 = 0;
    game_serve(g, 1);
}

static bool hits_paddle(const Game *g, int paddle_x, int paddle_y)
{
    return g->ball_x < paddle_x + PADDLE_W && g->ball_x + BALL_SIZE > paddle_x &&
           g->ball_y < paddle_y + PADDLE_H && g->ball_y + BALL_SIZE > paddle_y;
}

void game_update(Game *g, uint32_t input)
{
    if (input & IN_P1_UP) g->p1_y -= PADDLE_SPEED;
    if (input & IN_P1_DOWN) g->p1_y += PADDLE_SPEED;
    if (input & IN_P2_UP) g->p2_y -= PADDLE_SPEED;
    if (input & IN_P2_DOWN) g->p2_y += PADDLE_SPEED;
    g->p1_y = clamp(g->p1_y, 0, GAME_H - PADDLE_H);
    g->p2_y = clamp(g->p2_y, 0, GAME_H - PADDLE_H);

    g->ball_x += g->ball_dx;
    g->ball_y += g->ball_dy;
    if (g->ball_y <= 0 || g->ball_y >= GAME_H - BALL_SIZE) {
        g->ball_dy = -g->ball_dy;
        g->ball_y = clamp(g->ball_y, 0, GAME_H - BALL_SIZE);
    }

    const int left_x = PADDLE_MARGIN;
    const int right_x = GAME_W - PADDLE_MARGIN - PADDLE_W;
    if (g->ball_dx < 0 && hits_paddle(g, left_x, g->p1_y)) {
        g->ball_dx = -g->ball_dx;
        g->ball_x = left_x + PADDLE_W;
    } else if (g->ball_dx > 0 && hits_paddle(g, right_x, g->p2_y)) {
        g->ball_dx = -g->ball_dx;
        g->ball_x = right_x - BALL_SIZE;
    }

    if (g->ball_x + BALL_SIZE < 0) {
        g->score2++;
        game_serve(g, -1);
    } else if (g->ball_x > GAME_W) {
        g->score1++;
        game_serve(g, 1);
    }
}
