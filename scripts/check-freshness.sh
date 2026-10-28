#!/usr/bin/env bash
# Compare the commit each note was read at (docs/repo-versions.tsv) with the repo's current main.
# Prints FRESH, or STALE with the changed files grouped by the note section they affect.
#
#   scripts/check-freshness.sh                 all repos
#   scripts/check-freshness.sh matrix echo     only these (short names)
#   scripts/check-freshness.sh --bump matrix   record main's current commit as "read" (run AFTER the notes are updated)
#
# Needs only git and read access to the repos. Env: VERS_FILE, AREAS_FILE override the tables (for tests).
set -u
cd "$(dirname "$0")/.."
VERS="${VERS_FILE:-docs/repo-versions.tsv}"
AREAS="${AREAS_FILE:-docs/repo-areas.tsv}"
BASE="https://github.com"

bump=0
if [ "${1:-}" = "--bump" ]; then bump=1; shift; fi
want=("$@")

wanted() {
  [ ${#want[@]} -eq 0 ] && return 0
  local short="${1#*/}" w
  for w in "${want[@]}"; do [ "$w" = "$short" ] && return 0; done
  return 1
}

stale=0
while IFS=$'\t' read -r repo sha note; do
  case "$repo" in ''|\#*) continue ;; esac
  wanted "$repo" || continue
  new=$(git ls-remote "$BASE/$repo" refs/heads/main 2>/dev/null | cut -f1)
  if [ -z "$new" ]; then echo "UNKNOWN  $repo: cannot reach the repo (no access?)"; stale=1; continue; fi

  if [ $bump -eq 1 ]; then
    tmp=$(mktemp)
    awk -F'\t' -v OFS='\t' -v r="$repo" -v n="$new" '$1==r{$2=n}1' "$VERS" > "$tmp" && mv "$tmp" "$VERS"
    echo "BUMPED   $repo -> ${new:0:8}"
    continue
  fi

  if [ "$sha" = "$new" ]; then echo "FRESH    $repo @ ${sha:0:8}"; continue; fi

  work=$(mktemp -d)
  ( cd "$work" && git init -q && git remote add origin "$BASE/$repo" \
    && git fetch -q --depth=1 origin "$sha" "$new" ) >/dev/null 2>&1
  if [ ! -d "$work/.git" ] || ! git -C "$work" cat-file -e "$sha^{commit}" 2>/dev/null; then
    echo "STALE    $repo: ${sha:0:8} -> ${new:0:8} (old commit not fetchable; re-read the whole repo)"
    stale=1; rm -rf "$work"; continue
  fi
  all=$(git -C "$work" diff --name-only "$sha" "$new")
  # Release noise (version bumps, lockfiles) never changes what the notes say.
  files=$(printf '%s\n' "$all" | grep -Ev '(^|/)(package\.json|package-lock\.json|yarn\.lock|uv\.lock|pnpm-lock\.yaml)$')
  count=$(printf '%s\n' "$files" | grep -c .)
  noise=$(( $(printf '%s\n' "$all" | grep -c .) - count ))
  if [ "$count" -eq 0 ]; then
    echo "FRESH    $repo: ${sha:0:8} -> ${new:0:8}, only release files changed ($noise); run --bump ${repo#*/}"
    rm -rf "$work"; continue
  fi
  stale=1
  echo "STALE    $repo: ${sha:0:8} -> ${new:0:8}, $count files changed, $noise release-only files ignored (note: $note)"
  mapped=""; unmapped=""
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    hit=$(awk -F'\t' -v r="$repo" -v f="$f" '$1==r && index(f,$2)==1 {print $3; exit}' "$AREAS")
    if [ -n "$hit" ]; then mapped+="           $f  ->  $hit"$'\n'; else unmapped+="           $f"$'\n'; fi
  done <<< "$files"
  [ -n "$mapped" ] && { echo "  affects the notes:"; printf '%s' "$mapped"; }
  [ -n "$unmapped" ] && { echo "  not covered by any note area (tests, docs, CI, or a new area):"; printf '%s' "$unmapped" | head -15; }
  rm -rf "$work"
done < "$VERS"
exit $stale
