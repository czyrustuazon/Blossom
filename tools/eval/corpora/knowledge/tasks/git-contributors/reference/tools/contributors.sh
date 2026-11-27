#!/usr/bin/env bash
# Contributors of a revision range (default HEAD) for the release notes, one per line:
#   <commits>\t<Name> <email>
# most credited first, then by name. A commit credits its author and everyone in its
# Co-authored-by: trailers (once per commit). .mailmap applies to both; emails are compared
# case-insensitively and printed in lowercase; the name comes from the newest commit. Merges are skipped.
set -euo pipefail

range="${1:-HEAD}"

order=$(git log --no-merges --format='%H' "$range")
[ -n "$order" ] || exit 0

authors=$(git log --no-merges --format='%H%x09%aN <%aE>' "$range")

coauthors=$(git log --no-merges --format='%H%x09%(trailers:key=Co-authored-by,valueonly,separator=%x09)' "$range" |
    awk -F'\t' '{ for (i = 2; i <= NF; i++) if ($i ~ /<[^>]+>/) print $1 "\t" $i }')
if [ -n "$coauthors" ]; then
    coauthors=$(paste <(cut -f1 <<<"$coauthors") <(cut -f2- <<<"$coauthors" | git check-mailmap --stdin))
fi

printf '%s\n%s\n' "$authors" "$coauthors" |
    awk -F'\t' -v order="$order" '
        BEGIN { n = split(order, hashes, "\n"); for (i = 1; i <= n; i++) seq[hashes[i]] = i }
        NF >= 2 {
            ident = $2
            lt = index(ident, "<")
            name = substr(ident, 1, lt - 1); sub(/[ \t]+$/, "", name)
            email = tolower(substr(ident, lt + 1)); sub(/>.*$/, "", email)
            if (!((email SUBSEP $1) in seen)) { seen[email, $1] = 1; count[email]++ }
            if (!(email in best) || seq[$1] < best[email]) { best[email] = seq[$1]; who[email] = name }
        }
        END { for (e in count) printf "%d\t%s <%s>\n", count[e], who[e], e }' |
    LC_ALL=C sort -t$'\t' -k1,1nr -k2,2
