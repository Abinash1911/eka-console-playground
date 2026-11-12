# Header ribbon: widget, embed and console

A one-line message under the widget header (offer, privacy note, anything short). Set per agent in the console, or by the host page. Built separately from the welcome card (`patches/welcome-card/`); either can be taken alone.

## Settings
| Setting | Console field | Widget (`theme.ribbon`) | API shape (`theme.ribbon` in agent theme JSON) |
|---|---|---|---|
| Message | text (empty turns it off) | `text` | `text` |
| Fixed or dismissable | toggle "Users can close it" | `dismissable` (default fixed) | `dismissable` |
| Icon | None, Gift, Info, Megaphone, Sparkles, Shield, or **Upload your own** (file or https URL) | `icon`, or `iconUrl` (https image, wins over `icon`) | `icon`, or `icon_img` (the uploaded image's URL) |
| Background colour | colour picker (empty: accent colour) | `background` (hex) | `background` |
| Text colour | colour picker (empty: black or white, whichever reads better) | `textColor` (hex) | `text_color` |
| "Closed" memory key | not in the console (the text is the key, so new text shows again) | `id` | `id` |

A dismissed ribbon stays closed for that agent in that browser. Only hex colours (`#rgb`, `#rrggbb`), the five icons and https icon URLs are accepted; anything else is ignored. A custom icon upload must be an image up to 1 MB (our addition: the existing theme images are not size-checked); it is saved to public media storage like the other theme images, so in local dev (relative `/media/...` URL) the widget will not draw it until it is on https.

## The patches (apply in order, on the base commits below)
| # | Repo | Base | File | What |
|---|---|---|---|---|
| 1 | synapse-sdk | `bbb7405` (main, 2026-11-07) | `synapse-sdk/0001-*.patch` | Widget: the ribbon, colours, icons, "closed" memory, tests |
| 2 | synapse-sdk | after 1 | `synapse-sdk/0002-*.patch` | Embed loader: carries `theme.ribbon` from the agent config into the widget |
| 3 | dev-console | `862976e` (main, 2026-11-12; also applies on `36eb96b`) | `dev-console/0001-*.patch` | Console: "Header Ribbon" block in the agent's General tab, saved in the theme JSON |
Readable copies in `*/code/`. Screenshots in `screenshots/`. 1 and 3 are independent of each other; 2 needs 1. No database migration (the theme is a JSON column) and no matrix change (matrix returns `theme` as an untyped dict).

## How it is linked (one chain, checked end to end)
```
console General tab form (Header Ribbon block, multipart: text, icon / icon file / icon URL, toggle, 2 colours)
  -> agents/views/agent.py save: resolve_icon_img (+ _save_theme_image for an upload) and build_ribbon -> agent.theme["ribbon"]   (JSON column, no migration)
  -> matrix GET .../agent-config/<id>  returns theme as-is (untyped dict)                                                      (no change)
  -> widget-embed mapAgentConfigThemeToWidgetTheme: ribbon{text, dismissable, icon, icon_img, background, text_color} -> theme.ribbon{... iconUrl, textColor}   (patch 2)
  -> widget WidgetContainer -> HeaderRibbon (lazy) -> HeaderRibbonView                                                          (patch 1)
```
`scripts/check-ribbon-chain.sh` (in this repo) runs the chain: console save logic on a simulated form post (with an upload) -> the agent-config response -> the real embed + real widget in a browser, 9 checks (shows, text, background, text colour, uploaded icon URL and loaded, close button, closing hides it, stays closed after reload). Last run: 9/9 pass. Only the matrix hop is by reading (see Not tested).

## Checks
- Widget (1 and 2 on `bbb7405`): `tsc -b` clean; CI's `tsc -p tsconfig.vitest.json --noEmit` clean; vitest 408 passed (398 on main); `npm run build` + bundle budget OK (entry +152 B raw / +43 B gzip, ribbon is a lazy chunk); embed `tsc` clean. eslint: nothing new (main already has errors in `useChatWidget.ts`).
- All three synapse-sdk patches (ribbon x2 + welcome card) apply together with `git am --3way`.
- Console (3 on `862976e`): 15 new DB-free tests for the save and icon logic pass (run with a bare Django settings object, not the repo's test runner); the patched `detail.html` compiles as a Django template; `ThemeConfig` accepts and rejects as intended; patch applies with `git am`.
- Looked at in a real browser:
  - the widget through the mock server (`prototypes/widget`): fixed, dismissable, stays closed after reload;
  - the **real embed + real widget bundle**, with the agent-config call answered by a test response carrying `theme.ribbon` (screenshot `embed-end-to-end.png`): the ribbon shows with the saved text, icon and colours;
  - the console form block: the real HTML from the patched template with the repo's own Tailwind build and Alpine, in a stand-alone page (screenshots `console-form*.png`): typing, icon, upload your own (file and URL, https check, clear), toggle, colour pickers, clear buttons, preview, values posted (the file included), saved values load back.

## Not tested
- The real console page and save: the Django app was not run (no database, no secrets); `build_ribbon` and `resolve_icon_img` are tested, the view change only compiles. The file upload to public storage (`_save_theme_image`) was not run (replaced by a stub in tests).
- The Eka Console Prototype artifact's new ribbon block: its new JavaScript was run in Node with stubs (12 checks) but the published page was not opened in a browser.
- A real agent-config response from matrix (the test response imitates its shape; matrix passes `theme` through, read not run).
- Mobile, side panel, dark mode, screen readers, RTL; very long text.
- The public agents API (`ThemeRequest`) is not changed, so a ribbon can only be set from the console form for now.
- No reward logic: the ribbon is only text.

## Deviations / additions (ours, not from a spec)
- Names and the icon list are ours; "Behavior"/"Header Ribbon" labels follow the existing form wording.
- Same two small storage helpers exist in `useRibbonDismiss.ts` and, privately, in `useChatWidget.ts`; a developer may want one shared helper.
- The console preview approximates the widget (accent colour fallback, same black/white rule).
