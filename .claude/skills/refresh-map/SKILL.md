---
name: refresh-map
description: Bring the harness notes in docs/ up to date with the team's latest commits. Use before building anything that touches a repo, when asked to "refresh the map", and in the weekly scheduled refresh. Compares the commit each note was read at with the repo's current main, re-reads only the changed areas, corrects the notes, and records the new commit.
---

# Refresh the map

The notes in `docs/repos/`, `docs/how-it-fits.md`, `docs/capability-index.md` and `docs/build-recipes.md` were read from code at the commits listed in `docs/repo-versions.tsv`. The team keeps merging. This skill keeps the notes true.

## 1. Check
```
scripts/check-freshness.sh              # all repos
scripts/check-freshness.sh matrix echo  # only the repos you are about to touch
```
- `FRESH`: nothing to do (if it says only release files changed, run `--bump <repo>`).
- `STALE`: the output lists changed files, grouped by the note section each affects (from `docs/repo-areas.tsv`). Files listed as "not covered" may mean a new area: decide whether a note needs one and add a row to `repo-areas.tsv`.
- `UNKNOWN`: the repo could not be reached; say so, do not guess. Repos are attached to the session or readable if public.

## 2. Re-read only what changed
For each changed file that maps to a note: read the new version (clone shallow to a scratch folder such as `/tmp/ro/<repo>` and open the file; do not rely on the diff alone). Follow the repo's own rules in `CLAUDE.md`.
Apply the harness rules: two-ended check (producer and consumer), confidence labels, re-check earlier claims that touch the change.

## 3. Update
- Fix the sentences in the repo note, `how-it-fits.md`, `capability-index.md`, `build-recipes.md` that the change makes wrong. Prefer small edits to rewrites.
- If a change reverses something already told to the user, add a line under "Corrections" in `docs/build-log.md`.
- If a change affects a claim in `docs/claims-to-confirm.md`, update or close it.
- New or removed tools, endpoints, settings, dataset types, display modes, or skills must appear in `capability-index.md`.

## 4. Record
`scripts/check-freshness.sh --bump <repo>` (only after the notes are updated), then add a dated line to `docs/build-log.md`: repo, old and new commit, what changed in the notes. Commit with a short message and push to this repo's `main` (standing permission for harness updates only; never to a company repo).

## 5. Report to the user (under 100 words)
Which repos moved, what in the notes changed, anything that now contradicts a build in progress, anything you could not judge.

## Limits
- This reads `main` only. Work in unmerged branches and PRs is invisible until merged.
- The script reports files, not meaning. A one-line change to a default or a SQL string can matter more than a large refactor, so read mapped files rather than skimming the diff.
- Notes cover how things work, not why. Ask a developer when intent matters.
