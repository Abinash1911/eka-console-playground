# Header banner: widget, embed and console

One line of text under the widget header (an offer, a privacy note, anything short). Built from the review of synapse-sdk PR 218 (Geethanjali): the config is **one string, `theme.banner`**, and every colour comes from the accent colour. (The first version, named "ribbon", also had icon, upload icon, dismissable, background and text colours; all removed on review, on purpose.)

## The setting
| Where | Shape |
|---|---|
| Console (agent General tab, "Banner") | one text box, up to **200 characters including spaces**, live counter; empty turns it off |
| Agent theme JSON (what the agent-config API returns) | `theme.banner`: a string |
| Host page | `{ theme: { banner: "Chat and earn coins" } }` in the embed `theme` attribute or `init({ theme })` |
| Widget | `bg-primary text-primary-foreground`, always shown, no close button; trimmed; empty means none |

The console cuts at 200 and turns line breaks into spaces; the widget does not limit length (long text wraps).

## The patches (base commits)
| # | Repo | Base | Files | What |
|---|---|---|---|---|
| 1-3 | synapse-sdk | `bbb7405` (main, 2026-11-07) | `synapse-sdk/0001..0003-*.patch` | Same three commits as PR 218 (the first two are the original ribbon, the third simplifies it to `theme.banner`). Net change vs main: `HeaderBanner` component + test, one line in `WidgetContainer`, the type key in 3 places, one line in the embed loader |
| 1 | dev-console | `862976e` (main, 2026-11-12) | `dev-console/0001-*.patch` | Banner field in the General tab, saved as `theme.banner`; save logic in `agents/services/banner.py` + 5 DB-free tests |
Readable copies in `*/code/`. Screenshots in `screenshots/`. No database migration (theme is a JSON column), no matrix change (matrix returns `theme` as an untyped dict; read).

## How it is linked
```
console General tab (Banner text box) -> agents/views/agent.py: clean_banner -> agent.theme["banner"]   (JSON column)
  -> matrix GET .../agent-config/<id> returns theme as-is                                                  (no change)
  -> widget-embed mapAgentConfigThemeToWidgetTheme: banner -> theme.banner                                 (synapse-sdk PR)
  -> widget WidgetContainer -> HeaderBanner                                                                 (synapse-sdk PR)
```
`scripts/check-banner-chain.sh` runs it: console save logic -> agent-config response -> real embed + real widget in a browser, 5 checks (shows, text, no inline colours, background is the accent colour, no close button). Last run: 5/5 pass. The matrix hop is by reading only.

## Checks
- Widget + embed (on `bbb7405`): `tsc -b` clean; CI's `tsc -p tsconfig.vitest.json --noEmit` clean; vitest 394 pass (main: 391; 3 new); `npm run build` + bundle budget OK, entry +256 B raw / +66 B gzip (310,741 / 96,073 of 312,000 / 96,500); embed `tsc` clean.
- Console (on `862976e`): 5 new DB-free tests pass (run with a bare Django settings object, not the repo's runner); patched `detail.html` compiles as a Django template; patch applies with `git am`.
- Seen in a browser: the real embed + widget bundle with a test agent-config response; the console field in a stand-alone page with the repo's Tailwind build (type, counter, 250 pasted stops at 200, saved text loads back).
- Applies together with the welcome card patch (`git am --3way`).

## Not tested
- The running Django app and a real save (no database here); the view change only compiles.
- A real matrix response; mobile, dark mode, screen readers, RTL.
- The Eka Console Prototype artifact edit (not opened in a browser).
- No reward logic. The banner is only text; counting messages and paying out needs a backend.

## Deviations / additions (ours, not from a spec)
- Names (`banner`, `theme_banner`, `HeaderBanner`) follow the review; the 200-character cap and "line breaks become spaces" are ours.
- `ThemeRequest` (public API) is not changed.
