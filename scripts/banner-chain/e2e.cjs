// Step 2: the real embed + real widget bundle, answered with the config from step 1.
const { chromium } = require('playwright');
const fs = require('fs');
const [,, configPath, pageUrl] = process.argv;
const config = fs.readFileSync(configPath, 'utf8');
const banner = JSON.parse(config).data.theme.banner;
const checks = [];
const check = (name, ok, got) => { checks.push(ok); console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (ok ? '' : '  got: ' + JSON.stringify(got))); };

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1000, height: 760 } });
  await ctx.route(/agent-config/, (r) => r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: config }));
  await ctx.route(/^https?:\/\/(?!localhost)/, (r) => /agent-config/.test(r.request().url()) ? r.fallback() : r.abort());
  const p = await ctx.newPage();
  await p.goto(pageUrl); await p.waitForTimeout(2500);
  await p.locator('eka-medassist-widget').locator('#medassist-open-btn').click({ timeout: 8000 });
  await p.waitForTimeout(4500);
  const el = p.locator('eka-medassist-widget').locator('.synapse-header-banner');
  check('banner shows', (await el.count()) === 1, await el.count());
  check('text is the saved text', (await el.innerText()).trim() === banner, await el.innerText());
  check('no inline colours (derived from the accent colour)', (await el.getAttribute('style')) === null, await el.getAttribute('style'));
  const colours = await el.evaluate((n) => { const s = getComputedStyle(n); return { bg: s.backgroundColor, fg: s.color }; });
  // The widget turns the accent into an HSL token, so channels can differ by a point or two from #215fff = rgb(33, 95, 255).
  const [r, g, bl] = (colours.bg.match(/\d+/g) || []).map(Number);
  check('background is the accent colour #215fff (within 3 per channel)', Math.abs(r - 33) <= 3 && Math.abs(g - 95) <= 3 && Math.abs(bl - 255) <= 3, colours);
  check('no close button (always shown)', (await el.locator('button').count()) === 0, null);
  await p.screenshot({ path: process.env.SHOT || '/tmp/claude-0/chain.png' });
  await b.close();
  process.exit(checks.every(Boolean) ? 0 : 1);
})();
