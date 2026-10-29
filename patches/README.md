# Patches

Code we build for the company repos lives here as patches, never as copies of the repos.

Layout: `patches/<feature>/<repo>/NNNN-short-name.patch`, plus `NOTES.md` per feature (what changed, what is untested, assumptions for reviewers) and a `code/` folder with the changed files readable.

Rules
- Each patch applies on the latest `main` of its repo (`git am` or `git apply`). Record the base commit in `NOTES.md`.
- Re-make patches when `main` moves. Run the repo's own checks first and report the numbers.
- Nothing is pushed to a company repo or opened as a PR until the user says so; then new branch only.
- Say plainly what was not tested live.
