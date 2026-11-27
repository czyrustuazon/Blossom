#!/usr/bin/env bash
# Prints everyone who has committed, one per line.
set -euo pipefail

git log --format='%an <%ae>' | sort -u
