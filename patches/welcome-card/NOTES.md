# Welcome card (synapse-sdk widget)

A card on the empty first screen, set by the host. Built separately from the header ribbon (`patches/header-ribbon/`); either can be taken alone.

Patch: `patches/welcome-card/synapse-sdk/0001-*.patch` (applies with plain `git am` on synapse-sdk `bbb7405`, main 2026-11-07). Readable copies in `synapse-sdk/code/`. Screenshots in `screenshots/`.

## Config (host `theme.welcomeCard`, via the embed `theme` attribute or `init({ theme })`)
`{ title, body?, steps?, icon?, dismissable?, dismissLabel?, id? }`
- `title`: headline. Empty or missing means no card.
- `body`: one or two sentences.
- `steps`: up to three short labels, drawn as numbered circles.
- `icon`: `"gift"` (default), `"info"` or `"none"`.
- `dismissable`: "Maybe later" link (`dismissLabel` changes the text); stays hidden for this agent in this browser. Default false (fixed).
- `id`: change it to show the card again to people who dismissed an older one. Defaults to `title`.
The card disappears once the user has sent a message, whether fixed or dismissable.

## What changed
- New: `types/welcomeCard.ts`, `molecules/banner/WelcomeCardView.tsx` (drawing), `molecules/banner/WelcomeCard.tsx` (reads agent id from the store, remembers "dismissed"), `hooks/useWelcomeCardDismiss.ts`, tests.
- Edited: `organisms/ChatWidget.tsx` (renders it above the greeting, lazy; also passes it to the full-page empty state), `molecules/chat/EmptyStateFullScreen.tsx` (new `welcomeCard` slot), `hooks/useChatWidget.ts` (`hasUserMessage`, type key), `main.tsx` (type key).
- Fixed cards never touch storage. Dismissable ones write `welcome_card_dismissed:<id>` into the same per-agent store as the feedback and consent flags.

## Checks (run on this patch alone, on `bbb7405`)
- `tsc -b`: clean. `vitest`: 405 passed (398 on main). `npm run build` + bundle budget: OK, entry +278 B raw / +130 B gzip (310,763 / 96,137 of 312,000 / 96,500). The card is its own lazy chunk.
- eslint: no new problems (main already has 1 error in `EmptyStateFullScreen.tsx`, 2 in `useChatWidget.ts`).
- Both patches together (`git am --3way`): tsc clean, 416 tests pass, budget OK (entry 310,908 raw / 96,181 gzip). Plain `git am` of the second one fails on neighbouring import lines; `--3way` resolves it.
- Looked at in a real browser (mock server, `prototypes/widget`): floating widget and full page, with and without a greeting (the full-page empty-state slot), fixed and dismissable, stays dismissed after reload, disappears after sending a message or tapping a suggestion, absent without config.

## Not tested
- Through the real embed, and the agent-config API (see `docs/claims-to-confirm.md` 26).
- Mobile, side panel, dark mode, screen readers, RTL, long titles or bodies.
- A past session reopened from history (the card should stay hidden because the chat has user messages; not run).
- No reward logic. Steps are labels, not a live counter.

## Deviations / additions (ours, not from a spec)
- Names `welcomeCard`, `steps`, `dismissLabel` are ours.
- Same two small storage helpers as the ribbon patch and as `useChatWidget.ts` (private there).
