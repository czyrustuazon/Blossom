# release-tools

Scripts we run when cutting a release.

- `tools/contributors.sh [<range>]`: the people to thank in the release notes, for a revision range
  (default `HEAD`), as `<commits><TAB><Name> <email>` lines, most commits first, then by name. Authors
  and `Co-authored-by:` trailers both count (once per commit); `.mailmap` applies to both; emails are
  matched case-insensitively and printed in lowercase; merge commits are skipped.

`python -m pytest -q tests` builds throwaway git repositories and runs the scripts in them with bash
(msys2/Git for Windows bash on Windows).
