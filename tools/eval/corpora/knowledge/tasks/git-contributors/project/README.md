# release-tools

Scripts we run when cutting a release.

- `tools/contributors.sh`: the people to thank in the release notes.

`python -m pytest -q tests` builds throwaway git repositories and runs the scripts in them with bash
(msys2/Git for Windows bash on Windows).
