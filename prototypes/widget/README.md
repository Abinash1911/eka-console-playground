# Widget prototype (mock, real widget code)

Runs the real widget from a clean synapse-sdk checkout, with the repo's own `MockSynapseSDK` instead of a server.
We never edit synapse-sdk. Only added logic: a canned reply (`core-mocked.ts`).

1. Terminal: `cd /home/user/synapse-sdk/packages/widget && npm ci`  (once)
2. Terminal: `ln -sfn /home/user/synapse-sdk/packages/widget/node_modules prototypes/widget/node_modules`  (once)
3. Terminal: `cd /home/user/synapse-sdk/packages/widget && npx vite --config /home/user/eka-console-playground/prototypes/widget/vite.config.ts`
4. Browser: open http://localhost:5199 and send a message.

Try a change: apply a patch to synapse-sdk, the page hot-reloads. Other cards: in the browser console use `synapse.emit(...)` with builders from `src/test/fixtures.ts`.
Env `SYNAPSE_SDK` changes the checkout path.
