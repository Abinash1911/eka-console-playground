#!/usr/bin/env bash
# Is the header ribbon connected from the console form to the widget?
#   1. console save logic (dev-console patch)  -> the agent-config response
#   2. real embed (synapse-sdk patch 2) + real widget (patch 1), answered with that response, in a real browser
# Needs: clones of dev-console (branch with the ribbon patch) and synapse-sdk (branch feat/header-ribbon) with `npm install` done in
# packages/widget and packages/widget-embed, python3, node, Playwright. Env: SDK, DC override the clone paths. SKIP_BUILD=1 skips the builds.
set -euo pipefail
SDK="${SDK:-/home/user/synapse-sdk}"; DC="${DC:-/home/user/dev-console}"
HERE="$(cd "$(dirname "$0")" && pwd)"; CFG="$(mktemp --suffix=.json)"
export DC
python3 "$HERE/ribbon-chain/make_config.py" > "$CFG"; echo "console save logic -> $(python3 -c "import json,sys;print(json.dumps(json.load(open('$CFG'))['data']['theme']['ribbon'],ensure_ascii=False))")"
if [ "${SKIP_BUILD:-}" != "1" ]; then
  (cd "$SDK/packages/widget" && npm run build-dev >/dev/null 2>&1)
  (cd "$SDK/packages/widget-embed" && npm run build:with-widget >/dev/null 2>&1)
fi
cp "$HERE/ribbon-chain/page.html" "$SDK/packages/widget-embed/chain-page.html"
(cd "$SDK/packages/widget-embed" && python3 -m http.server 5311 >/dev/null 2>&1 & echo $! > "$CFG.pid"); sleep 1
trap 'kill "$(cat "$CFG.pid")" 2>/dev/null; rm -f "$SDK/packages/widget-embed/chain-page.html" "$CFG" "$CFG.pid"' EXIT
NODE_PATH="${NODE_PATH:-$(npm root -g)}" node "$HERE/ribbon-chain/e2e.cjs" "$CFG" "http://localhost:5311/chain-page.html"
