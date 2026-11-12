// Step 2: the real embed + real widget bundle, answered with the config from step 1.
const { chromium } = require('playwright');
const fs = require('fs');
const [,, configPath, pageUrl] = process.argv;
const config = fs.readFileSync(configPath, 'utf8');
const ribbon = JSON.parse(config).data.theme.ribbon;
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAEElEQVR4nGP4z8DwHx1jMAMA6fMT8W3bsREAAAAASUVORK5CYII=', 'base64');
const checks = [];
const check = (name, ok, got) => { checks.push(ok); console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (ok ? '' : '  got: ' + JSON.stringify(got))); };

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1000, height: 760 } });
  await ctx.route(/agent-config/, (r) => r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: config }));
  await ctx.route(ribbon.icon_img, (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG }));
  await ctx.route(/^https?:\/\/(?!localhost)/, (r) => /agent-config|cdn\.eka\.care\/1\//.test(r.request().url()) ? r.fallback() : r.abort());
  const open = async () => {
    const p = await ctx.newPage();
    await p.goto(pageUrl); await p.waitForTimeout(2500);
    await p.locator('eka-medassist-widget').locator('#medassist-open-btn').click({ timeout: 8000 });
    await p.waitForTimeout(4500);
    return p;
  };
  let p = await open();
  const r = p.locator('eka-medassist-widget').locator('.synapse-header-ribbon');
  check('ribbon shows', (await r.count()) === 1, await r.count());
  check('text is the saved text', (await r.innerText()).trim() === ribbon.text, await r.innerText());
  const style = (await r.getAttribute('style')) || '';
  check('background is the saved background', /background-color:\s*rgb\(30,\s*58,\s*138\)/.test(style), style);
  check('text colour is the saved text colour', /color:\s*rgb\(255,\s*213,\s*74\)/.test(style), style);
  const img = r.locator('img');
  check('uploaded icon is drawn from the saved URL', (await img.count()) === 1 && (await img.getAttribute('src')) === ribbon.icon_img, await img.getAttribute('src'));
  check('uploaded icon actually loaded', await img.evaluate((i) => i.complete && i.naturalWidth > 0), null);
  const close = r.getByRole('button', { name: 'Dismiss' });
  check('close button shown (dismissable)', (await close.count()) === 1, await close.count());
  await p.screenshot({ path: process.env.SHOT || '/tmp/claude-0/chain.png' });
  await close.click(); await p.waitForTimeout(400);
  check('closing hides it', (await r.count()) === 0, await r.count());
  await p.close(); p = await open();
  check('stays closed after a reload', (await p.locator('eka-medassist-widget').locator('.synapse-header-ribbon').count()) === 0, null);
  await b.close();
  process.exit(checks.every(Boolean) ? 0 : 1);
})();
