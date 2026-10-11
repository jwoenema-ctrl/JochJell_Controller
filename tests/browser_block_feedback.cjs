/* Physical detector assignment UI with disposable simulation data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-block-feedback-'));
let server, browser;
async function start() {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', 'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); print(server.server_port, flush=True); server.serve_forever()', path.join(scratch, 'controller.sqlite3')], { cwd: path.resolve(__dirname, '..'), windowsHide: true });
  let errors = '';
  server.stderr.on('data', data => { errors += data; });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(errors || 'Server startup timed out')), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.stdout.once('data', data => { clearTimeout(timer); resolve(`http://127.0.0.1:${String(data).trim()}`); });
  });
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  const done = new Promise(resolve => server.once('exit', resolve)); server.kill(); await done;
}
(async () => {
  let url = await start();
  browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function ready() {
    await page.goto(url + '/#settings');
    await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  }
  async function open() {
    await page.locator('#open-feedback-mapping').click();
    await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments loaded.');
  }
  async function add(module, input) {
    await page.locator('#feedback-add-contact').click();
    const row = page.locator('.feedback-contact-row').last();
    await row.locator('[data-feedback-module]').fill(String(module));
    await row.locator('[data-feedback-input]').fill(String(input));
  }
  async function save() {
    await page.locator('#feedback-save').click();
    await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments saved on this controller.');
  }
  async function selectSystem(system) {
    await page.locator('#feedback-system').selectOption(system);
    await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments loaded.');
  }
  await ready(); await open();
  assert.equal(await page.locator('#feedback-system').inputValue(), 'z21');
  await page.locator('#feedback-block').selectOption('B02');
  await add(1, 1); await add(1, 2); await save();
  assert.equal(await page.locator('.feedback-contact-row').count(), 2);
  let payload = await (await page.request.get(url + '/api/block-feedback?system=z21')).json();
  assert.equal(payload.assignments.length, 2);
  assert.equal(payload.physical, false, 'Assignments do not connect hardware');
  await selectSystem('ecos');
  assert.equal(await page.locator('.feedback-contact-row').count(), 0, 'Other profiles have separate assignments');
  await page.locator('#feedback-block').selectOption('B03');
  await add(1, 16); await save();
  await selectSystem('z21');
  await page.locator('#feedback-block').selectOption('B03');
  await add(1, 1); await page.locator('#feedback-save').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent.startsWith('Not saved:'));
  assert.match(await page.locator('#feedback-save-status').textContent(), /already assigned to block B02/);
  assert.equal(await page.locator('.feedback-contact-row').count(), 1, 'Failed save retains draft');
  await page.locator('#feedback-discard').click();
  assert.equal(await page.locator('.feedback-contact-row').count(), 0);
  await page.locator('#feedback-block').selectOption('B02');
  const trigger = { id: 'shared', block_id: 'B02', detector: { module: 1, input: 1 }, actions: [{ type: 'function', function_number: 0, mode: 'on' }] };
  const triggerResponse = await page.request.post(url + '/api/commands', { data: { type: 'save_track_trigger', trigger } });
  assert.ok(triggerResponse.ok());
  await page.locator('[data-feedback-close]').click(); await open();
  await page.locator('#feedback-block').selectOption('B02');
  assert.match(await page.locator('#feedback-inherited-rows').textContent(), /used by a track trigger/);
  await page.locator('.feedback-contact-row').first().getByRole('button', { name: 'Remove detector input' }).click();
  await save();
  assert.equal(await page.locator('.feedback-contact-row').count(), 1);
  payload = await (await page.request.get(url + '/api/block-feedback?system=z21')).json();
  assert.equal(payload.assignments.length, 2, 'Inherited trigger mapping stays present after removing its independent assignment');
  await page.route('**/api/commands', route => route.request().postDataJSON()?.type === 'set_block_feedback' ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Test save failure' }) }) : route.continue());
  await add(2, 3); await page.locator('#feedback-save').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent.startsWith('Not saved:'));
  assert.equal(await page.locator('.feedback-contact-row').count(), 2);
  await page.locator('#feedback-discard').click();
  await page.unroute('**/api/commands');
  await page.route('**/api/block-feedback?system=ecos', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Test load failure' }) }));
  await page.locator('#feedback-system').selectOption('ecos');
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent.startsWith('Unable to load'));
  assert.equal(await page.locator('#feedback-save').isDisabled(), true, 'Failed load cannot overwrite assignments');
  await page.unroute('**/api/block-feedback?system=ecos');
  await page.locator('[data-feedback-close]').click();
  await stop(); url = await start(); await ready(); await open();
  await page.locator('#feedback-block').selectOption('B02');
  assert.equal(await page.locator('.feedback-contact-row').count(), 1, 'Independent assignment survives restart');
  assert.equal(await page.locator('[data-feedback-input]').inputValue(), '2');
  await page.locator('#feedback-overview-rows').evaluate(node => node.closest('details').open = true);
  if (process.env.SCREENSHOT_DIR) {
    fs.mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.locator('#block-feedback-editor').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'block-feedback-desktop.png') });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
  assert.ok(await page.locator('#block-feedback-editor').evaluate(node => node.scrollWidth <= node.clientWidth + 2), 'Mobile dialog fits');
  if (process.env.SCREENSHOT_DIR) await page.locator('#block-feedback-editor').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'block-feedback-mobile.png') });
  await page.locator('[data-feedback-close]').click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: 'Automation', exact: true }).click();
  await page.locator('.block-node').first().dblclick();
  await page.locator('#edit-block-feedback').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments loaded.');
  assert.equal(await page.locator('#feedback-block').inputValue(), (await page.locator('#block-id').inputValue()).toUpperCase(), 'Block editor shortcut selects its block');
  assert.equal(await page.locator('#block-editor').evaluate(node => node.open), true, 'Underlying block draft remains open');
  await page.locator('[data-feedback-close]').click();
  assert.equal(await page.locator('#block-editor').evaluate(node => node.open), true);
  assert.deepEqual(errors, []);
  console.log('PASS: hardware block UI, multiple inputs, profile isolation, conflicts, inherited mappings, save/load failures, restart, mobile, and block editor shortcut.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close(); await stop();
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-block-feedback-')) fs.rmSync(scratch, { recursive: true, force: true });
});
