/* Hidden acceptance sample: repeated calls, a call through a function-pointer table (only a
   data reference to the target), and an imported function reached through its import thunk. */
#include <stdio.h>
#include <stdlib.h>

#define KEEP __attribute__((noipa))

KEEP unsigned decrypt_block(unsigned x)
{
    return (x ^ 0x5a5a5a5au) * 2654435761u;
}

KEEP unsigned read_config(void)
{
    const char *v = getenv("SAMPLE_KEY");
    return decrypt_block(v ? (unsigned)atoi(v) : 7u);
}

KEEP unsigned stream(unsigned n)
{
    unsigned acc = 0;
    for (unsigned i = 0; i < n; i++)
        acc += decrypt_block(i);
    return acc + decrypt_block(acc);
}

unsigned (*volatile handlers[2])(unsigned) = { decrypt_block, decrypt_block };

KEEP unsigned via_table(unsigned i)
{
    return handlers[i & 1](i);
}

int main(int argc, char **argv)
{
    (void)argv;
    if (getenv("SAMPLE_DEBUG"))
        puts("debug");
    printf("%u\n", read_config() + stream((unsigned)argc) + via_table(3));
    return 0;
}
