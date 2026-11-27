#include <3ds.h>
#include <citro2d.h>
#include <stdio.h>

#include "render.h"

static C3D_RenderTarget *top;
static C3D_RenderTarget *bottom;
static C2D_TextBuf static_buf; /* parsed once */
static C2D_TextBuf score_buf;  /* cleared and re-parsed every frame */
static C2D_Text help_text;

void render_init(void)
{
    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);
    C2D_Init(C2D_DEFAULT_MAX_OBJECTS);
    C2D_Prepare();
    top = C2D_CreateScreenTarget(GFX_TOP, GFX_LEFT);
    bottom = C2D_CreateScreenTarget(GFX_BOTTOM, GFX_LEFT);

    static_buf = C2D_TextBufNew(64);
    score_buf = C2D_TextBufNew(32);
    C2D_TextParse(&help_text, static_buf, "START: quit  D-Pad/ABXY: move");
    C2D_TextOptimize(&help_text);
}

void render_frame(const Game *g)
{
    const u32 black = C2D_Color32(0, 0, 0, 255);
    const u32 white = C2D_Color32(255, 255, 255, 255);
    const u32 grey = C2D_Color32(90, 90, 90, 255);
    const u32 ball = C2D_Color32(255, 200, 0, 255);

    char score[16];
    snprintf(score, sizeof score, "%d - %d", g->score1, g->score2);
    C2D_Text score_text;
    C2D_TextBufClear(score_buf);
    C2D_TextParse(&score_text, score_buf, score);
    C2D_TextOptimize(&score_text);

    C3D_FrameBegin(C3D_FRAME_SYNCDRAW);

    C2D_TargetClear(top, black);
    C2D_SceneBegin(top);
    for (int y = 0; y < GAME_H; y += 16)
        C2D_DrawRectSolid(GAME_W / 2 - 1, y, 0, 2, 8, grey);
    C2D_DrawRectSolid(PADDLE_MARGIN, g->p1_y, 0, PADDLE_W, PADDLE_H, white);
    C2D_DrawRectSolid(GAME_W - PADDLE_MARGIN - PADDLE_W, g->p2_y, 0, PADDLE_W, PADDLE_H, white);
    C2D_DrawRectSolid(g->ball_x, g->ball_y, 0, BALL_SIZE, BALL_SIZE, ball);
    C2D_DrawText(&score_text, C2D_WithColor | C2D_AlignCenter, GAME_W / 2.0f, 8, 0, 0.8f, 0.8f, white);

    C2D_TargetClear(bottom, black);
    C2D_SceneBegin(bottom);
    C2D_DrawText(&help_text, C2D_WithColor, 8, 8, 0, 0.5f, 0.5f, white);

    C3D_FrameEnd(0);
}

void render_exit(void)
{
    C2D_TextBufDelete(score_buf);
    C2D_TextBufDelete(static_buf);
    C2D_Fini();
    C3D_Fini();
}
