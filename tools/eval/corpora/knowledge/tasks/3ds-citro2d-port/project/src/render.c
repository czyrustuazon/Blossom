#include <3ds.h>
#include <stdio.h>
#include <string.h>

#include "render.h"

/* The top screen framebuffer is 240x400, rotated 90 degrees, BGR8. */
static void fill_rect(u8 *fb, int x, int y, int w, int h, u8 r, u8 g, u8 b)
{
    for (int px = x; px < x + w; px++) {
        if (px < 0 || px >= GAME_W)
            continue;
        for (int py = y; py < y + h; py++) {
            if (py < 0 || py >= GAME_H)
                continue;
            u8 *p = fb + ((px * GAME_H) + (GAME_H - 1 - py)) * 3;
            p[0] = b;
            p[1] = g;
            p[2] = r;
        }
    }
}

/* Seven-segment digit, 12x20, segments a..g. */
static void draw_digit(u8 *fb, int x, int y, int d)
{
    static const u8 seg[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};
    const u8 s = seg[d % 10];
    if (s & 0x01) fill_rect(fb, x, y, 12, 2, 255, 255, 255);
    if (s & 0x02) fill_rect(fb, x + 10, y, 2, 10, 255, 255, 255);
    if (s & 0x04) fill_rect(fb, x + 10, y + 10, 2, 10, 255, 255, 255);
    if (s & 0x08) fill_rect(fb, x, y + 18, 12, 2, 255, 255, 255);
    if (s & 0x10) fill_rect(fb, x, y + 10, 2, 10, 255, 255, 255);
    if (s & 0x20) fill_rect(fb, x, y, 2, 10, 255, 255, 255);
    if (s & 0x40) fill_rect(fb, x, y + 9, 12, 2, 255, 255, 255);
}

static void draw_number(u8 *fb, int x, int y, int n)
{
    if (n >= 10) {
        draw_digit(fb, x, y, n / 10);
        x += 16;
    }
    draw_digit(fb, x, y, n);
}

void render_init(void)
{
    gfxSetDoubleBuffering(GFX_TOP, true);
    consoleInit(GFX_BOTTOM, NULL);
    printf("START: quit  D-Pad/ABXY: move\n");
}

void render_frame(const Game *g)
{
    u8 *fb = gfxGetFramebuffer(GFX_TOP, GFX_LEFT, NULL, NULL);
    memset(fb, 0, GAME_W * GAME_H * 3);

    for (int y = 0; y < GAME_H; y += 16)
        fill_rect(fb, GAME_W / 2 - 1, y, 2, 8, 90, 90, 90);
    fill_rect(fb, PADDLE_MARGIN, g->p1_y, PADDLE_W, PADDLE_H, 255, 255, 255);
    fill_rect(fb, GAME_W - PADDLE_MARGIN - PADDLE_W, g->p2_y, PADDLE_W, PADDLE_H, 255, 255, 255);
    fill_rect(fb, g->ball_x, g->ball_y, BALL_SIZE, BALL_SIZE, 255, 200, 0);

    draw_number(fb, GAME_W / 2 - 40, 10, g->score1);
    draw_number(fb, GAME_W / 2 + 24, 10, g->score2);
}

void render_exit(void)
{
}
