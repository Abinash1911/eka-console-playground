# PR descriptions

## synapse-sdk (PR open: https://github.com/eka-care/synapse-sdk/pull/218)
Already on GitHub; the text there is the current one (title "Header banner: one line of text under the widget header (theme.banner)").

---
## dev-console: "Banner text in the agent's General tab"  (not raised yet; push was blocked, see docs/pending.md)
Base: `main` (`862976e` when built). One commit. Patch file: `patches/header-banner/dev-console/`.

**What**: a "Banner" field in the Appearance form: one line of text (up to 200 characters including spaces, with a live counter) shown under the widget header; empty turns it off. Saved as `theme.banner` (a string) in the agent's theme JSON. Colours follow the accent colour, so there is nothing else to set. No migration; matrix needs no change (it returns `theme` as an untyped dict).
**Why**: product wants an offer or notice per agent without a code change per customer. Pairs with synapse-sdk PR 218, which draws it.
**Notes for review**
- Save logic is `clean_banner` in `agents/services/banner.py` (pure Python, `agents/test_banner.py`, DB-free, 5 tests): trims, turns runs of whitespace and line breaks into one space, cuts at 200.
- `ThemeConfig` documents the key; `ThemeRequest` (public API) is deliberately not changed.
- The field sits between "Toggle Header Color" and "Feedback Form".
**Tested**: the 5 tests; the patched `detail.html` compiles as a Django template; the field rendered in a browser with the repo's Tailwind build (type, counter, paste 250 stops at 200, saved text loads back).
**Not tested**: the running app (no database here), so the real save.
**Pairs with**: https://github.com/eka-care/synapse-sdk/pull/218
