/* Disposable layout verifies rail ownership, boundaries, colour persistence and responsive UI. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-track-blocks-'));
let server, browser;
async function start() {
  const code = 'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); app.stop_motion_clock(); print(server.server_port, flush=True); server.serve_forever()';
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', code, path.join(scratch, 'controller.sqlite3')], { cwd: path.resolve(__dirname, '..'), windowsHide: true });
  let errors = '';
  server.stderr.on('data', data => { errors += data; });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(errors || 'Startup timed out')), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.stdout.once('data', data => { clearTimeout(timer); resolve('http://127.0.0.1:' + String(data).trim()); });
  });
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  const done = new Promise(resolve => server.once('exit', resolve)); server.kill(); await done;
}
async function shot(page, name) {
  if (!process.env.SCREENSHOT_DIR) return;
  fs.mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
  await page.locator('#layout-panel').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, name + '.png') });
}
(async () => {
  let url = await start();
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  async function state() { return (await page.request.get(url + '/api/state')).json(); }
  async function ready() {
    await page.goto(url + '/#layout');
    await page.waitForFunction(() => document.querySelector('#block-count').textContent === '4');
    await page.locator('[data-layout-view="pinboard"]').click();
    await page.locator('#track-block-legend').waitFor({ state: 'visible' });
  }
  async function select(index = 0) {
    const section = page.locator(`.pinboard-track-section[data-spline-edge="0"][data-spline-index="${index}"]`);
    await section.focus(); await section.press('Enter');
  }
  await ready();
  assert.equal(await page.locator('.pinboard-node').count(), 0, 'Normal view represents blocks on rails');
  assert.equal(await page.locator('[data-track-block]').count(), 4);
  await page.locator('#toggle-layout-edit').click();
  await page.locator('[data-layout-view="pinboard"]').click();
  assert.equal(await page.locator('.pinboard-node').count(), 4, 'Editing retains geometry anchors');
  await select();
  await page.locator('#spline-section-block').selectOption('B01');
  await page.waitForTimeout(1200);
  assert.equal(await page.locator('#spline-section-block').inputValue(), 'B01', 'Polling preserves unsaved block selection');
  await page.locator('#save-spline-section-block').click();
  await page.waitForFunction(() => document.querySelector('.pinboard-track-section[data-spline-edge="0"]').dataset.trackOwner === 'b01');
  await page.locator('#spline-section-speed').fill('45');
  await page.locator('#save-spline-section-speed').click();
  await page.locator('#spline-section-split').fill('30');
  await page.locator('#split-block-boundary').click();
  await page.waitForFunction(() => document.querySelectorAll('.pinboard-track-section[data-spline-edge="0"]').length === 2);
  assert.equal(await page.locator('.pinboard-track-section[data-spline-edge="0"][data-track-owner="b01"]').count(), 2);
  assert.equal(await page.locator('[data-boundary-anchor="WP02"]').count(), 0, 'Shared owner has no artificial boundary');
  await select(1);
  await page.locator('#spline-section-block').selectOption('B02');
  await page.locator('#save-spline-section-block').click();
  await page.waitForFunction(() => !!document.querySelector('[data-boundary-anchor="WP02"]'));
  await page.locator('[data-track-block="b01"]').click();
  await page.locator('#edit-selected-block').click();
  await page.locator('#block-color').fill('#e85d75');
  await page.locator('#save-block-editor').click();
  await page.waitForFunction(() => !document.querySelector('#block-editor').open);
  assert.equal(await page.locator('[data-track-owner="b01"] .pinboard-rail').evaluate(node => getComputedStyle(node).stroke), 'rgb(232, 93, 117)');
  assert.equal(await page.locator('[data-track-owner="b01"] .pinboard-rail.is-occupied').count(), 1, 'Owner supplies occupancy status');
  const result = await page.request.post(url + '/api/commands', { data: { type: 'set_track_section', from: 'B02', to: 'B03', start_anchor_id: 'B02', end_anchor_id: 'B03', block_id: 'B01' } });
  assert.ok(result.ok(), await result.text());
  await page.waitForFunction(() => document.querySelectorAll('[data-track-owner="b01"]').length === 2);
  assert.equal(await page.locator('[data-track-owner="b01"] .pinboard-rail').evaluateAll(nodes => new Set(nodes.map(node => getComputedStyle(node).stroke)).size), 1, 'Multiple tracks share the block colour');
  await page.locator('#save-layout').click();
  await page.waitForFunction(() => document.querySelector('#toast-region').textContent.toLowerCase().includes('saved'));
  await shot(page, 'track-blocks-editor-desktop');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) <= 2, 'Editor fits mobile width');
  await shot(page, 'track-blocks-editor-mobile');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('#toggle-layout-edit').click();
  await page.locator('[data-layout-view="pinboard"]').click();
  assert.equal(await page.locator('.pinboard-node, .pinboard-spline-point').count(), 0);
  await shot(page, 'track-blocks-desktop');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) <= 2);
  await shot(page, 'track-blocks-mobile');
  await stop(); url = await start(); await ready();
  const restored = await state();
  assert.equal(restored.layout.blocks.find(b => b.id === 'b01').color, '#e85d75');
  assert.equal(await page.locator('[data-track-owner="b01"]').count(), 2);
  assert.equal(await page.locator('[data-boundary-anchor="WP02"]').count(), 1);
  assert.deepEqual(errors, []);
  console.log('PASS: multi-track blocks, persistent colours and boundaries, occupancy outlines, keyboard selection, preserved drafts, desktop/mobile layouts and restart.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close(); await stop();
  const resolved = path.resolve(scratch);
  if (path.dirname(resolved) === path.resolve(os.tmpdir()) && path.basename(resolved).startsWith('h0-track-blocks-')) fs.rmSync(resolved, { recursive: true, force: true });
});
