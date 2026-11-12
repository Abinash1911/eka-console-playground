# Header ribbon: widget, embed and console

A one-line message under the widget header (offer, privacy note, anything short). Set per agent in the console, or by the host page. Built separately from the welcome card (`patches/welcome-card/`); either can be taken alone.

## Settings
| Setting | Console field | Widget (`theme.ribbon`) | API shape (`theme.ribbon` in agent theme JSON) |
|---|---|---|---|
| Message | text (empty turns it off) | `text` | `text` |
| Fixed or dismissable | toggle "Users can close it" | `dismissable` (default fixed) | `dismissable` |
| Icon | None, Gift, Info, Megaphone, Sparkles, Shield | `icon` | `icon` |
| Background colour | colour picker (empty: accent colour) | `background` (hex) | `background` |
| Text colour | colour picker (empty: black or white, whichever reads better) | `textColor` (hex) | `text_color` |
| "Closed" memory key | not in the console (the text is the key, so new text shows again) | `id` | `id` |

A dismissed ribbon stays closed for that agent in that browser. Only hex colours (`#rgb`, `#rrggbb`) and the five icons are accepted; anything else is ignored.

## The patches (apply in order, on the base commits below)
| # | Repo | Base | File | What |
|---|---|---|---|---|
| 1 | synapse-sdk | `bbb7405` (main, 2026-11-07) | `synapse-sdk/0001-*.patch` | Widget: the ribbon, colours, icons, "closed" memory, tests |
| 2 | synapse-sdk | after 1 | `synapse-sdk/0002-*.patch` | Embed loader: carries `theme.ribbon` from the agent config into the widget |
| 3 | dev-console | `36eb96b` (main, 2026-11-12) | `dev-console/0001-*.patch` | Console: "Header Ribbon" block in the agent's General tab, saved in the theme JSON |
Readable copies in `*/code/`. Screenshots in `screenshots/`. 1 and 3 are independent of each other; 2 needs 1. No database migration (the theme is a JSON column) and no matrix change (matrix returns `theme` as an untyped dict).

## Checks
- Widget (1 and 2 on `bbb7405`): `tsc -b` clean; vitest 406 passed (398 on main); `npm run build` + bundle budget OK (entry +152 B raw / +43 B gzip, ribbon is a lazy chunk); embed `tsc` clean. eslint: nothing new (main already has errors in `useChatWidget.ts`).
- All three synapse-sdk patches (ribbon x2 + welcome card) apply together with `git am --3way`.
- Console (3 on `36eb96b`): 7 new DB-free tests for the save logic pass (run with a bare Django settings object, not the repo's test runner); the patched `detail.html` compiles as a Django template; `ThemeConfig` accepts and rejects as intended; patch applies with `git am`.
- Looked at in a real browser:
  - the widget through the mock server (`prototypes/widget`): fixed, dismissable, stays closed after reload;
  - the **real embed + real widget bundle**, with the agent-config call answered by a test response carrying `theme.ribbon` (screenshot `embed-end-to-end.png`): the ribbon shows with the saved text, icon and colours;
  - the console form block: the real HTML from the patched template with the repo's own Tailwind build and Alpine, in a stand-alone page (screenshots `console-form*.png`): typing, icon, toggle, colour pickers, clear buttons, preview, values posted, saved values load back.

## Not tested
- The real console page and save: the Django app was not run (no database, no secrets); `build_ribbon` is tested, the view change only compiles.
- A real agent-config response from matrix (the test response imitates its shape; matrix passes `theme` through, read not run).
- Mobile, side panel, dark mode, screen readers, RTL; very long text.
- The public agents API (`ThemeRequest`) is not changed, so a ribbon can only be set from the console form for now.
- No reward logic: the ribbon is only text.

## Deviations / additions (ours, not from a spec)
- Names and the icon list are ours; "Behavior"/"Header Ribbon" labels follow the existing form wording.
- Same two small storage helpers exist in `useRibbonDismiss.ts` and, privately, in `useChatWidget.ts`; a developer may want one shared helper.
- The console preview approximates the widget (accent colour fallback, same black/white rule).
