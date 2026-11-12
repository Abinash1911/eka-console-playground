# Header ribbon (synapse-sdk widget)

A one-line message under the widget header, set by the host. Built separately from the welcome card (`patches/welcome-card/`); either can be taken alone.

Patch: `patches/header-ribbon/synapse-sdk/0001-*.patch` (applies with plain `git am` on synapse-sdk `bbb7405`, main 2026-11-07). Readable copies in `synapse-sdk/code/`. Screenshots in `screenshots/`.

## Config (host `theme.ribbon`, via the embed `theme` attribute or `init({ theme })`)
`{ text, dismissable?, icon?, id? }`
- `text`: the message. Empty or missing means no ribbon.
- `dismissable`: close button; stays closed for this agent in this browser. Default false (fixed).
- `icon`: `"gift"` or `"info"`. Default none.
- `id`: change it to show the ribbon again to people who closed an older one. Defaults to `text`.

## What changed
- New: `types/ribbon.ts`, `molecules/banner/HeaderRibbonView.tsx` (drawing), `molecules/banner/HeaderRibbon.tsx` (reads agent id from the store, remembers "closed"), `hooks/useRibbonDismiss.ts`, tests.
- Edited: `organisms/WidgetContainer.tsx` (renders it under the header, lazy), type key added in `main.tsx` and `hooks/useChatWidget.ts`.
- Fixed ribbons never touch storage. Dismissable ones write `ribbon_dismissed:<id>` into the same per-agent store as the feedback and consent flags.

## Checks (run on this patch alone, on `bbb7405`)
- `tsc -b`: clean. `vitest`: 402 passed (398 on main). `npm run build` + bundle budget: OK, entry +152 B raw / +43 B gzip (310,637 / 96,050 of 312,000 / 96,500). The ribbon is its own lazy chunk.
- eslint: no new problems (main already has 2 errors in `useChatWidget.ts`).
- Looked at in a real browser (mock server, `prototypes/widget`): fixed ribbon, dismissable ribbon, stays closed after reload, absent without config, sending a message works with it. Screenshots saved.

## Not tested
- Through the real embed (`<eka-medassist-widget theme='{...}'>`): I did not check that the embed passes `theme.ribbon` through to the widget.
- Agent-config API: `theme.ribbon` is not mapped from the API (embed `mapAgentConfigThemeToWidgetTheme`), so a console setting would need backend + embed work. See `docs/claims-to-confirm.md` 26.
- Mobile, side panel, dark mode, screen readers, RTL. The ribbon uses `bg-primary text-primary-foreground`, so contrast follows the agent's accent colour.
- No reward logic. The ribbon is only text.

## Deviations / additions (ours, not from a spec)
- Names `ribbon`, `dismissable`, `icon`, `id` are ours.
- Same two small storage helpers exist in `useRibbonDismiss.ts` and in `useChatWidget.ts` (`readAgentFlag`/`writeAgentFlag`, private there). A developer may want one shared helper.
