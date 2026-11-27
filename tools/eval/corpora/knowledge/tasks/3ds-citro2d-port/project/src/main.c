#include <3ds.h>

#include "game.h"
#include "render.h"

static uint32_t read_input(u32 held)
{
    uint32_t in = 0;
    if (held & KEY_DUP) in |= IN_P1_UP;
    if (held & KEY_DDOWN) in |= IN_P1_DOWN;
    if (held & KEY_X) in |= IN_P2_UP;
    if (held & KEY_B) in |= IN_P2_DOWN;
    return in;
}

int main(void)
{
    gfxInitDefault();
    render_init();

    Game game;
    game_reset(&game);

    while (aptMainLoop()) {
        hidScanInput();
        if (hidKeysDown() & KEY_START)
            break;
        game_update(&game, read_input(hidKeysHeld()));
        render_frame(&game);

        gfxFlushBuffers();
        gfxSwapBuffers();
        gspWaitForVBlank();
    }

    render_exit();
    gfxExit();
    return 0;
}
