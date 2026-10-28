# synapse-sdk (chat widget)

Read from code at `d3c8268` (v0.2.117). Monorepo, TypeScript, React 18 + Zustand + Tailwind. Rules in the root and per-package `CLAUDE.md`.

## Packages
| Package | Role |
|---|---|
| `packages/core` (`@synapse/core`) | The single source of truth: `SynapseSDK` class, enums (events, components, elicitation status, error codes, channels), connection (WebSocket or HTTP stream), session, auth, tool calls, feedback, files, audio, voice |
| `packages/widget` (`@eka-care/medassist-widget`) | The React UI built on core. Exports `renderMedAssist`, `prefetchAuth`, `fetchAgentConfig` (also on `window`) |
| `packages/widget-embed` (`@eka-care/medassist-widget-embed`) | The `<eka-medassist-widget>` custom element and `EkaMedAssist.init()`: a launcher in a Shadow DOM that lazy-loads the widget bundle (from jsDelivr/unpkg) on first click. Also an iframe helper |
Core never imports widget. Widget never reaches into core internals.

## Runtime flow
```
host page: <eka-medassist-widget agent-id="..."> + script
  embed: reads attributes + init() config, fetches agent config (GET matrix agent-config), draws launcher
  click: loads widget bundle, renderMedAssist(container, agentId, config)
  SynapseSDK.startSession(): ensureCredentials() (token exchange: guest, or partner token; refresh) -> create session (POST) or resume -> connect (WebSocket or HTTP stream)
  events from server -> SynapseSDK.on(...) -> useChat (all listeners, routing) -> Zustand store -> components
  user input -> useChat.sendMessage -> callTool (answer an elicitation) or SDK.sendMessage (chat)
```
Headers sent on API calls include `x-channel` (`widget`, `web` for full page, `side_panel`, `center`) and the widget version.

## Layers (who may do what)
| Layer | Owns |
|---|---|
| core | transport, session, tokens, events |
| `useChat.tsx` | **all** SDK calls, event listeners, message routing, elicitation state |
| `useChatWidget.ts` | shared UI logic (state, handlers, effects, display mode, sizes) |
| `medAssistStore.ts` | UI state (connection, streaming, errors, elicitation map) |
| `ChatWidget.tsx` | layout only |
| `WidgetContainer.tsx` | mode-specific layout, drag, side panel push, mobile viewport handling |
| leaf components | render and fire callbacks |

## Display modes
`widget` (floating 384x600, draggable, optional resize toggle), `full` (fullscreen with history sidebar), `side_panel` (docked 320-560px, push or overlay, left/right), mobile (full viewport; chosen by `useResolvedMode`: width up to 768px, coarse pointer or mobile user agent). Added in our branches (not merged): `center` (search bar + dialog), configurable floating size (PR 214). `displayMode` is not persisted; each mount reseeds from config.

## Elicitation (agent asks, UI answers)
Server sends a tool event with `component` (`pill`, `multi`, `card`, `doctor_card`, `mobile`, `otp`, `email`, `media_card`), `status` (`progress`, `success`, `failure`) and `input` (what to draw) plus `_meta.schema` (what to send next).
- `elicitationState` is a map keyed `"${messageId}::${toolId}"`.
- `active` gates routing (answers go to the tool callback, not the LLM); `disabled` is UI-only. Never mix them.
- `server_input` accumulates fields for the tool call (merged, never replaced); `input` is what is rendered.
- `send_to_llm` forwards the tool result to the model after success (doctor cards).
- Restored history renders read-only (`active:false, disabled:true`), the user's pick shown as a synthetic message.
- New component type: add the enum in core, a render branch in `ChatMessage`, and answer through `sendMessage({ toolCalled: true, tool_key, selectedComponent })`.

## Other features
Voice mode (`VoiceAgent`, WebRTC to matrix), file upload (presigned URLs via matrix), audio recording (transcribed server-side), feedback (message like/dislike, session NPS-style form on exit), consent and disclaimer modals, chat history (sidebar in full mode, drawer elsewhere; logged-in users only), theming (agent config `theme` plus host `theme` attribute/`init` overrides; `mergeTheme` keeps only colour keys, read non-colour settings from `config.theme`), nudge popup (embed), Google Tag Manager style host events through `window.trackWidgetEvent` when present.

## Embed attributes (host contract)
`agent-id` (required), `icon-url`, `title`, `base-url`, `display-mode`, `side-panel-mode`, `side-panel-width`, `side`, `context` (JSON), `theme` (JSON), `custom-launcher-styles`, `redirect-url`, `feedback`, `environment`, `resize`. `EkaMedAssist.init({...})` takes the same plus `theme`.

## Quality gates
`tsc -b`, vitest, eslint, `npm run build` (includes a gzip bundle budget `scripts/bundle-budget.json`, entry limit currently 95,500 bytes on main). Releases are made by GitHub Actions committing "chore(widget): release vX" (so a clone can look "behind" by bot commits).

## Where to change what
| Goal | Place |
|---|---|
| New elicitation UI | core enum, `ChatMessage` branch, `useChat` untouched if routing is generic |
| New display behaviour | `useResolvedMode`, `useChatWidget`, `WidgetContainer`, embed attribute list |
| New host option | embed `observedAttributes`, `loadAndRender`, `MedAssistInitConfig`, `useChatWidget` config, README |
| New API field from agent config | core `AgentConfigResponse`, embed `AgentConfig` + mapping, widget config |
