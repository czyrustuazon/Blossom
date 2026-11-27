#include <3ds.h>
#include <stdio.h>

#include "sound.h"

int main(void)
{
    gfxInitDefault();
    consoleInit(GFX_TOP, NULL);
    romfsInit();

    const bool have_sound = sound_init();
    printf("Sound test\n\nA: bounce  B: score  START: quit\n");
    if (!have_sound)
        printf("\nSound unavailable (running muted).\n");

    while (aptMainLoop()) {
        hidScanInput();
        const u32 down = hidKeysDown();
        if (down & KEY_START)
            break;
        if (down & KEY_A)
            sound_play(SFX_BOUNCE);
        if (down & KEY_B)
            sound_play(SFX_SCORE);
        gspWaitForVBlank();
    }

    sound_exit();
    romfsExit();
    gfxExit();
    return 0;
}
