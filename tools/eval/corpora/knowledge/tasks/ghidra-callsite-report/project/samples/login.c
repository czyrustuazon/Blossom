/* Sample target for the scripts in ghidra_scripts/. Built with gcc -O1 by tests/headless.py. */
#include <stdio.h>

#define KEEP __attribute__((noipa))

KEEP int checksum(const char *s)
{
    int h = 0;
    while (*s)
        h = h * 31 + *s++;
    return h;
}

KEEP int handle_login(const char *user)
{
    return checksum(user) & 0xff;
}

KEEP int handle_logout(const char *user)
{
    return checksum(user) ^ checksum("logout");
}

int main(int argc, char **argv)
{
    const char *user = argc > 1 ? argv[1] : "guest";
    printf("%d %d\n", handle_login(user), handle_logout(user));
    return 0;
}
