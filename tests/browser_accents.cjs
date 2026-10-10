/* Accent preferences on an isolated simulated controller. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-accent-test-'));
let server, browser;

async function startServer() {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', 'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); print(server.server_port, flush=True); server.serve_forever()', path.join(scratch, 'controller.sqlite3')], { cwd: path.resolve(__dirname, '..'), windowsHide: true });
  let errors = '';
  server.stderr.on('data', data => { errors += data; });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Server did not start: ${errors}`)), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); if (code) reject(new Error(errors)); });
    server.stdout.once('data', data => { clearTimeout(timer); resolve(`http://127.0.0.1:${String(data).trim()}`); });
  });
}
async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise(resolve => server.once('exit', resolve));
  server.kill(); await exited;
}
async function shot(page, name) {
  if (!process.env.SCREENSHOT_DIR) return;
  fs.mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
  const target = path.join(process.env.SCREENSHOT_DIR, `${name}.png`);
  if (name.startsWith('accent-settings')) await page.locator('#settings-appearance').screenshot({ path: target });
  else await page.screenshot({ path: target, fullPage: true });
}
async function verifyContrast(page) {
  await page.locator('.mode-tab.is-active, #settings-save').evaluateAll(nodes => Promise.all(nodes.flatMap(node => node.getAnimations().map(animation => animation.finished))));
  const result = await page.evaluate(() => {
    const rgb = color => color.match(/[\d.]+/g).slice(0, 3).map(Number);
    const luminance = channels => channels.map(channel => {
      const value = channel / 255;
      return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
    }).reduce((sum, value, i) => sum + value * [.2126, .7152, .0722][i], 0);
    const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
    const tab = getComputedStyle(document.querySelector('.mode-tab.is-active'));
    const button = getComputedStyle(document.querySelector('#settings-save'));
    const hover = document.documentElement.style.getPropertyValue('--primary-hover');
    const hoverRgb = [1, 3, 5].map(i => parseInt(hover.slice(i, i + 2), 16));
    return { tab: contrast(rgb(tab.color), rgb(tab.backgroundColor)), button: contrast(rgb(button.color), rgb(button.backgroundColor)), hover: contrast(rgb(button.color), hoverRgb) };
  });
  for (const [control, ratio] of Object.entries(result)) assert.ok(ratio >= 4.5, `${control} contrast ${ratio} must be at least 4.5`);
}

(async () => {
  let url = await startServer();
  browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, colorScheme: 'light' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${url}/#settings`);
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  assert.equal(await page.locator('html').getAttribute('data-accent'), 'graphite');
  const statusColors = () => page.evaluate(() => ['--red', '--green', '--yellow', '--orange', '--violet', '--occupied-bg', '--route-bg'].map(token => getComputedStyle(document.documentElement).getPropertyValue(token)));
  const baseline = await statusColors();
  const option = value => page.locator(`input[name="accent-color"][value="${value}"]`);
  await option('#3975de').check();
  assert.equal(await page.locator('html').getAttribute('data-accent'), '#3975de');
  assert.match(await page.locator('#settings-save-status').textContent(), /Unsaved/);
  assert.deepEqual(await statusColors(), baseline, 'Railway status colors must stay consistent');
  assert.equal((await (await page.request.get(`${url}/api/settings`)).json()).settings.accent_color, 'graphite', 'Preview must not persist');
  await page.locator('#settings-discard').click();
  assert.equal(await page.locator('html').getAttribute('data-accent'), 'graphite');
  await option('graphite').focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await option('#3975de').isChecked(), true, 'Radio choices support keyboard navigation');

  for (const theme of ['light', 'dark']) {
    await page.locator('#setting-theme').selectOption(theme);
    for (const preset of ['#3975de', '#168078', '#8056c4', '#ac642e']) {
      await option(preset).check(); await verifyContrast(page);
    }
    for (const custom of ['#ffffff', '#000000', '#ffff00', '#00ff00', '#ff0000', '#0000ff', '#123456']) {
      await page.locator('#setting-accent-custom').fill(custom);
      assert.equal(await option('custom').isChecked(), true);
      assert.equal(await page.locator('html').getAttribute('data-accent'), custom);
      await verifyContrast(page);
    }
    await option('#168078').check();
    await verifyContrast(page);
    await shot(page, `accent-settings-${theme}`);
  }
  await page.locator('#setting-theme').selectOption('system');
  await page.locator('#setting-accent-custom').fill('#123456');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal(await page.locator('html').getAttribute('data-accent'), '#123456', 'System theme changes preserve the draft');
  await verifyContrast(page);
  await page.locator('#settings-save').click();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent === 'Saved on this controller.');
  assert.equal((await (await page.request.get(`${url}/api/settings`)).json()).settings.accent_color, '#123456');
  await page.locator('#settings-accent-reset').click();
  assert.equal(await page.locator('html').getAttribute('data-accent'), 'graphite');
  await page.locator('#settings-discard').click();
  assert.equal(await page.locator('html').getAttribute('data-accent'), '#123456');
  await page.route('**/api/settings', route => route.request().method() === 'POST' ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Test save failure' }) }) : route.continue());
  await option('#168078').check();
  await page.locator('#settings-save').click();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.startsWith('Not saved:'));
  assert.equal(await page.locator('html').getAttribute('data-accent'), '#168078', 'Failed saves retain the draft');
  await page.locator('#settings-discard').click();
  assert.equal(await page.locator('html').getAttribute('data-accent'), '#123456');
  await page.unroute('**/api/settings');
  await stopServer(); url = await startServer();
  await page.goto(`${url}/#settings`);
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  assert.equal(await page.locator('html').getAttribute('data-accent'), '#123456', 'Custom preference survives restart');
  assert.equal(await page.locator('#setting-accent-custom').inputValue(), '#123456');
  await option('#168078').check();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), 'Mobile settings must fit');
  await shot(page, 'accent-settings-mobile');
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await shot(page, 'accent-home-dark');
  assert.deepEqual(errors, [], 'No browser errors');
  console.log('PASS: accents, keyboard, contrast in both themes, system theme, preview, save/discard/reset, failed save, restart, and mobile layout.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stopServer();
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-accent-test-')) fs.rmSync(scratch, { recursive: true, force: true });
});
