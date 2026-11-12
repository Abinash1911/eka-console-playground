# Ready-to-paste PR descriptions (nothing is opened yet)

Two PRs, one per repo, so developers only review and approve. Open them in this order; the widget one first, since the console form writes what the widget reads.

---
## synapse-sdk: "Header ribbon: a one-line message under the widget header"
Base: `main` (`bbb7405` when built). Two commits: `feat(widget): header ribbon (theme.ribbon)`, `feat(widget-embed): carry theme.ribbon from the agent config`. Patch files: `patches/header-ribbon/synapse-sdk/`.

**What**: a one-line ribbon under the header, for an offer or a notice. Settings: text, fixed or dismissable, icon (five presets or an uploaded image via `iconUrl`), background colour, text colour. Set by the host (`theme.ribbon` in the embed `theme` attribute or `init({ theme })`) or by the agent config (`theme.ribbon`, mapped by the embed loader).
**Why**: product wants to show offers and privacy notes without a code change per customer.
**Notes for review**
- Lazy-loaded (own chunk): entry grows 152 B raw / 43 B gzip; bundle budget passes.
- Only hex colours, five icons and https image URLs are accepted; anything else is ignored. With only a background, text is black or white by luminance.
- "Dismissed" is stored in the per-agent store that already holds `feedback_hidden`; its key is the ribbon text, so new text shows again. Same two small storage helpers now exist in `useRibbonDismiss.ts` and (private) in `useChatWidget.ts`: happy to share one.
- The embed's `AgentConfig.theme` type gets a `ribbon` key (snake_case: `text_color`, `icon_img`), matching what dev-console saves.
**Tested**: `tsc -b`, `tsc -p tsconfig.vitest.json --noEmit`, vitest 408 pass (398 on main), `npm run build` with the bundle check, embed `tsc`. Seen in a browser: the real embed and widget bundle with a test agent-config response (text, colours, uploaded icon, close, stays closed after reload).
**Not tested**: real matrix response; mobile, dark mode, screen readers, RTL.
**Pairs with**: the dev-console PR (settings form).

---
## dev-console: "Header ribbon settings in the agent's General tab"
Base: `main` (`862976e` when built; also applies on `36eb96b`). One commit. Patch file: `patches/header-ribbon/dev-console/`.

**What**: a "Header Ribbon" block in the Appearance form: text (up to 200 characters including spaces, with a live counter; empty turns it off), icon (preset, or upload your own image / https URL), fixed or dismissable, background and text colour, live preview. Saved as `theme.ribbon` in the agent's theme JSON (`{text, dismissable, icon | icon_img, background, text_color}`). No migration; matrix needs no change (it returns `theme` as an untyped dict).
**Notes for review**
- Save logic lives in `agents/services/ribbon.py` (pure Python, `agents/test_ribbon.py`, DB-free, 15 tests). The view only calls it.
- Uploads reuse `_save_theme_image` (public media). Added limits: image content type and 1 MB; https-only URLs (the widget ignores http).
- `ThemeConfig` documents the shape; `ThemeRequest` (public API) is deliberately not changed.
- The form block sits between "Toggle Header Color" and "Feedback Form"; the General form is already multipart.
**Tested**: the 15 tests; the patched `detail.html` compiles as a Django template; the form block rendered in a browser with the repo's Tailwind build (type, icon, upload, URL, clear, Fixed or Dismissable choice, colours, saved values load back).
**Not tested**: the running app (no database here): the real save and the upload to storage.
**Pairs with**: the synapse-sdk PR (widget + embed).
