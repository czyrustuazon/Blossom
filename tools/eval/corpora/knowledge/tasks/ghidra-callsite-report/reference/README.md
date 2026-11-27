# re-scripts

Ghidra scripts we run headless over builds of our own binaries.

- `ghidra_scripts/ListFunctions.java`: prints every function with its entry point and size.
- `ghidra_scripts/CallSiteReport.java`: `-postScript CallSiteReport.java <out.json> <name>...` writes the
  call sites (caller + call instruction address, sorted) of each named function, imports included.
- `samples/`: small C programs to try the scripts on.
- `tests/`: builds a sample with gcc and runs a script on it with Ghidra's `analyzeHeadless`
  (`GHIDRA_INSTALL_DIR`, default `C:\Program Files\ghidra_12.1.2`). Run with `python -m pytest -q tests`.
  One headless run takes about 20 seconds.
