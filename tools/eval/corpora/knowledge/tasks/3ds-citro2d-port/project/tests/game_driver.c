#include <stdio.h>

#include "game.h"

int main(void)
{
    Game g;
    game_reset(&g);
    printf("serve %d %d\n", g.ball_x, g.ball_y);

    for (int i = 0; i < 60; i++)
        game_update(&g, IN_P1_UP | IN_P2_DOWN);
    printf("clamp %d %d\n", g.p1_y, g.p2_y);

    game_reset(&g);
    g.p2_y = 0; /* right paddle away from the ball: player 1 scores */
    for (int i = 0; i < 80 && g.score1 == 0; i++)
        game_update(&g, 0);
    printf("score %d %d\n", g.score2, g.score1);

    game_reset(&g);
    for (int i = 0; i < 80 && g.ball_dx > 0; i++) {
        g.p2_y = g.ball_y - PADDLE_H / 2; /* keep the right paddle on the ball */
        game_update(&g, 0);
    }
    printf("bounce %d\n", g.ball_dx);
    return 0;
}
