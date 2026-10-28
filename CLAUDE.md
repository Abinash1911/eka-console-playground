# CLAUDE.md: standing rules for AI work on the Eka console and chat widget

These rules load every session. Keep them short; remove any that stop helping.

## Who and why
The user is a product manager, not an engineer. Goal: build features in the real repos' own language, style and quality so developers can review and ship with little rework. Reduce developer time.

## How to answer
- Keep replies under 100 words unless asked for detail.
- Plain language, no jargon. For setup, give numbered steps one at a time.
- Say what was verified and what was not tested. Never imply a live test happened if it did not.
- If an answer rests on a partial read, say so and name what was not read.

## Never without being asked
- Never push to `main` of a company repo. Never open a PR unless the user explicitly says to raise one.
- Build in private copies and deliver patches/zips until told to push.
- When told to push: new branch only, never touch someone else's branch (for example `feature/life-3141` holds another developer's work), never rewrite history on branches that are not ours.
- Never ask the user to paste secrets into chat. Credentials go in the environment's secret settings.
- Hook warnings about bot commits (github-actions) are not ours; do not amend them.

## Before building anything
0. Read `docs/how-it-fits.md` and the repo note in `docs/repos/` for the area; use `docs/build-recipes.md` for where to start.
1. Check whether it already exists: `docs/capability-index.md`, then the code in dev-console, synapse-sdk, matrix, echo, eka-mcp-sdk, eka-remote-mcp, doot, and developer.eka.care.
2. Do not call something "missing" after a code search alone. Read the files. State the files read.
2a. **Two-ended check.** A gap is real only after reading both ends: the code that produces the thing and the code that consumes it, plus what it is for. One-sided reads are labelled **inference**, never stated as fact.
2b. **Confidence label on every finding:** **verified** (both ends read), **partial** (one end, or search only), **inference** (reasoned, not read). Put the label in `docs/` notes and in answers.
2c. **Re-check on every new read.** After reading a repo, list earlier claims that touch it and re-test them. Write corrections in `docs/build-log.md` ("Corrections") so they are visible.
2e. **Freshness.** Before building, run `scripts/check-freshness.sh <repos you will touch>`. If stale, follow `.claude/skills/refresh-map/SKILL.md` first. Say in the answer which commits the notes were read at.
2d. Anything that would change a build decision goes to `docs/claims-to-confirm.md` for a developer to confirm before we build on it.
3. Use the repo's own code style. Anything beyond what the repos have is labelled as an addition.
4. Reuse a spec's naming exactly when one is given; list any deviation.

## When delivering
- Run the repo's own checks (type-check, tests, lint, build) and report numbers.
- Check visuals in a real browser where possible.
- Package as patches plus a readable `code/` folder, with notes on what changed and what is untested.

## Keep this harness alive
- Update `docs/build-log.md` after each feature or decision.
- When a step repeats, propose a skill or loop to the user.
- Each correction from the user becomes a rule here, if it will recur.
