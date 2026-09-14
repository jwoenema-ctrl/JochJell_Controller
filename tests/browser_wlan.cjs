/* Frontend-only WLAN settings integration. The controller stays simulated and
 * the desktop bridge is mocked, so this test can never touch physical hardware. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-wlan-ui-'));
let server, browser;

(async () => {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c',
    'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); s=make_server(port=0, application=app); print(s.server_port, flush=True); s.serve_forever()',
    path.join(scratch, 'controller.sqlite3')], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const port = await new Promise((resolve, reject) => {
    let stderr = '';
    server.stderr.on('data', data => { stderr += data; });
    server.once('error', reject);
    server.once('exit', code => reject(new Error(`Server exited ${code}: ${stderr}`)));
    server.stdout.once('data', data => resolve(String(data).trim()));
  });
  const url = `http://127.0.0.1:${port}`;
  let saved = { theme: 'system', z21_host: '192.168.0.111', z21_port: 21105, z21_wlan_enabled: false, ui_refresh_ms: 5000, routing: { adaptive: true, busy_interval_ms: 1000, idle_interval_ms: 5000 } };
  const runtime = () => ({
    transport_profile: saved.z21_wlan_enabled ? 'wlan_10814' : 'lan',
    next_transport_profile: saved.z21_wlan_enabled ? 'wlan' : 'lan',
    transport_status: { profile: saved.z21_wlan_enabled ? 'wlan' : 'lan', state: 'ready', ready: true, detail: 'UDP transport profile ready' },
    connection_message: 'Saving never activates hardware.',
    restart_required: false,
    routing: { activity: 'idle', effective_interval_ms: 5000, refresh_count: 1 }
  });
  browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [], bridgeCalls = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/settings', async route => {
    if (route.request().method() === 'POST') saved = { ...saved, ...route.request().postDataJSON() };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ settings: saved, runtime: runtime() }) });
  });
  await page.goto(`${url}/#settings`);
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));

  const wlan = page.locator('#setting-z21-wlan');
  assert.equal(await wlan.getAttribute('role'), 'switch');
  assert.match(await wlan.getAttribute('aria-describedby'), /setting-z21-wlan-help/);
  assert.equal(await wlan.isChecked(), false);
  assert.equal(await page.locator('#settings-connect-z21').textContent(), 'Connect to real Z21');
  assert.match(await page.locator('#setting-z21-wlan-help').textContent(), /does not join Wi-Fi/i);
  assert.match(await page.locator('#setting-z21-wlan-help').textContent(), /never stores its password/i);
  assert.equal(await page.locator('input[type="password"]').count(), 0, 'No Wi-Fi password control may be present');

  await page.evaluate(() => {
    window.__bridgeCalls = [];
    window.pywebview = { api: { switch_mode: async mode => { window.__bridgeCalls.push(mode); return { accepted: true, message: 'Mock desktop accepted WLAN profile.', transport_profile: 'wlan', transport_status: { profile: 'wlan', state: 'ready', ready: true, detail: 'UDP transport profile ready' } }; } } };
    window.dispatchEvent(new Event('pywebviewready'));
  });
  await page.locator('#setting-z21-host').fill('10.42.0.7');
  await wlan.check();
  assert.equal(await page.locator('#setting-z21-host').inputValue(), '10.42.0.7', 'Selecting WLAN retains a custom host');
  assert.equal(await page.locator('#settings-connect-z21').textContent(), 'Connect via WLAN');
  assert.equal(await page.locator('#settings-connect-z21').isDisabled(), true, 'Dirty settings cannot be used to connect');
  assert.match(await page.locator('#settings-native-status').textContent(), /Save or discard.*connecting via WLAN/i);
  assert.match(await page.locator('#settings-transport-status').textContent(), /Roco 10814 WLAN.*10\.42\.0\.7:21105/i);

  await page.locator('#settings-save').click();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent === 'Saved on this controller.');
  assert.equal(saved.z21_wlan_enabled, true, 'WLAN preference is sent through the existing settings API');
  assert.equal(saved.z21_host, '10.42.0.7');
  assert.equal(await page.locator('#settings-connect-z21').isEnabled(), true);
  assert.equal(await page.locator('#settings-transport-status').getAttribute('data-profile'), 'wlan');
  assert.equal(await page.locator('#settings-transport-status').getAttribute('data-check'), 'ok');
  assert.match(await page.locator('#settings-transport-status').textContent(), /Controller profile: Roco 10814 WLAN.*Connection check: UDP transport profile ready/i);

  await page.locator('#settings-connect-z21').click();
  await page.waitForFunction(() => document.querySelector('#settings-native-status').textContent === 'Mock desktop accepted WLAN profile.');
  bridgeCalls.push(...await page.evaluate(() => window.__bridgeCalls));
  assert.deepEqual(bridgeCalls, ['z21'], 'WLAN uses the existing confirmed Z21 desktop mode switch');

  await wlan.uncheck();
  assert.equal(await page.locator('#settings-connect-z21').textContent(), 'Connect to real Z21');
  await page.locator('#settings-discard').click();
  assert.equal(await wlan.isChecked(), true, 'Discard restores the saved WLAN preference');
  assert.equal(await page.locator('#settings-connect-z21').textContent(), 'Connect via WLAN');
  assert.equal(await page.locator('#setting-z21-host').inputValue(), '10.42.0.7');

  await page.reload();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  assert.equal(await wlan.isChecked(), true, 'Saved WLAN preference survives reload');
  assert.equal(await page.locator('#setting-z21-host').inputValue(), '10.42.0.7');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) <= 2, 'WLAN settings do not overflow mobile');
  assert.deepEqual(errors, []);
  console.log('PASS: accessible WLAN setting, honest guidance, persistence, dirty/discard flow, runtime status, native bridge mock, custom host, and mobile layout.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) { const exited = new Promise(resolve => server.once('exit', resolve)); server.kill(); await exited; }
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-wlan-ui-')) fs.rmSync(scratch, { recursive: true, force: true });
});
