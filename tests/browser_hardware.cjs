/* Registry/settings integration uses an isolated simulator. Physical connect
 * commands are intercepted, with a server-side guard against opening adapters. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'jochjell-hardware-ui-'));
let server, browser;

(async () => {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c',
    'from backend.api.server import ControllerApplication, make_server; from backend.runtime import ControllerRuntime; from unittest.mock import patch; import sys; original=ControllerRuntime.create_track; guard=patch("backend.runtime.ControllerRuntime.create_track", side_effect=lambda config, **kwargs: original(config, **kwargs) if config["system"] == "simulation" else (_ for _ in ()).throw(AssertionError("Browser test cannot open physical adapters"))); guard.start(); app=ControllerApplication.sample(database_path=sys.argv[1]); s=make_server(port=0, application=app); print(s.server_port, flush=True); s.serve_forever()',
    path.join(scratch, 'controller.sqlite3')], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  const port = await new Promise((resolve, reject) => {
    let stderr = '';
    server.stderr.on('data', data => { stderr += data; });
    server.once('error', reject);
    server.once('exit', code => reject(new Error(`Server exited ${code}: ${stderr}`)));
    server.stdout.once('data', data => resolve(String(data).trim()));
  });
  const url = `http://127.0.0.1:${port}`;
  browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [], intercepted = [];
  let failNextConnect = false, settingsReads = 0, liveReads = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.method() === 'GET' && request.url().endsWith('/api/settings')) settingsReads += 1; if (request.url().endsWith('/api/live')) liveReads += 1; });
  const settings = () => page.request.get(`${url}/api/settings`).then(response => response.json());
  await page.route('**/api/commands', async route => {
    const command = route.request().postDataJSON();
    const payload = await settings();
    if (command.type === 'connect_hardware' && payload.settings.hardware.system !== 'simulation') {
      intercepted.push(payload.settings.hardware.system);
      if (failNextConnect) {
        failNextConnect = false;
        await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'Test station connection failed; simulator active.' }) });
        return;
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ accepted: true, message: 'Intercepted test connection. No hardware was opened.', runtime: payload.runtime }) });
    } else await route.continue();
  });
  await page.goto(`${url}/#settings`);
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  const initial = await settings();
  const profiles = initial.hardware_profiles;
  assert.equal(profiles.length, 9, 'All requested station profiles are exposed');
  assert.equal(await page.locator('#setting-hardware-system option').count(), profiles.length);
  const save = async () => {
    await page.locator('#settings-save').click();
    await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent === 'Saved on this controller.');
  };
  for (const profile of profiles) {
    await page.locator('#setting-hardware-system').selectOption(profile.id);
    assert.match(await page.locator('#setting-hardware-help').textContent(), new RegExp(profile.detail.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.equal(await page.locator('#setting-z21-port').inputValue(), String(profile.default_port), `${profile.id} network port default`);
    assert.equal(await page.locator('#setting-hardware-baudrate').inputValue(), String(profile.default_baudrate), `${profile.id} serial speed default`);
    const serial = profile.transport === 'serial';
    const network = ['udp', 'tcp'].includes(profile.transport);
    assert.equal(await page.locator('#setting-hardware-host-row').isVisible(), network);
    assert.equal(await page.locator('#setting-hardware-port-row').isVisible(), network);
    assert.equal(await page.locator('#setting-hardware-serial-row').isVisible(), serial);
    assert.equal(await page.locator('.settings-wlan-row').isVisible(), network);
    assert.equal(await page.locator('#setting-hardware-protocol option').count(), profile.decoder_protocols.length);
    if (serial) await page.locator('#setting-hardware-serial').fill('COM20');
    if (network) {
      await page.locator('#setting-z21-host').fill('10.42.0.7');
      await page.locator('#setting-z21-wlan').check();
      assert.equal(await page.locator('#setting-z21-host').inputValue(), '10.42.0.7', 'Wi-Fi keeps the custom station IP');
      assert.equal(await page.locator('#settings-connect-z21').isDisabled(), true, 'Unsaved connection changes cannot activate hardware');
    }
    await save();
    const saved = (await settings()).settings.hardware;
    assert.equal(saved.system, profile.id);
    assert.equal(saved.transport, serial ? 'serial' : network ? 'wlan' : 'simulation');
    if (network) assert.equal(saved.host, '10.42.0.7');
    if (serial) assert.equal(saved.serial_port, 'COM20');
    assert.equal((await settings()).runtime.hardware_system, 'simulation', 'Saving a hardware profile leaves the active simulator untouched');
    if (profile.id !== 'simulation') {
      await page.locator('#settings-connect-z21').click();
      await page.waitForFunction(() => document.querySelector('#settings-native-status').textContent.includes('Intercepted test connection'));
    }
  }
  assert.equal(intercepted.length, profiles.length - 1, 'Every physical connect was intercepted');
  const settingsBeforeFailure = settingsReads, liveBeforeFailure = liveReads;
  failNextConnect = true;
  await page.locator('#settings-connect-z21').click();
  await page.waitForFunction(() => document.querySelector('#settings-native-status').textContent.includes('Test station connection failed'));
  assert.ok(settingsReads > settingsBeforeFailure && liveReads > liveBeforeFailure, 'A failed connect rereads both controller state and active settings');
  assert.equal((await settings()).runtime.hardware_system, 'simulation');
  await page.locator('#setting-hardware-system').selectOption('simulation');
  await save();
  await page.locator('#settings-connect-z21').click();
  await page.waitForFunction(() => /Simulation|simulation/.test(document.querySelector('#settings-native-status').textContent));
  assert.equal((await settings()).runtime.hardware_system, 'simulation');
  assert.equal((await settings()).runtime.hardware_connection.transport, 'simulation');
  await page.locator('#settings-use-simulation').click();
  await page.waitForFunction(() => /Simulation|simulation/.test(document.querySelector('#settings-native-status').textContent));
  assert.equal((await settings()).runtime.hardware_system, 'simulation');
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  assert.equal(await page.locator('#setting-hardware-system').inputValue(), 'simulation', 'Saved profile persists across reload');
  await page.setViewportSize({ width: 390, height: 844 });
  for (const id of ['z21', 'marklin_cs3', 'ecos', 'xpressnet']) {
    await page.locator('#setting-hardware-system').selectOption(id);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) <= 2, `${id} settings fit a mobile viewport`);
  }
  assert.deepEqual(errors, []);
  console.log('PASS: all nine hardware profiles/defaults, network Wi-Fi and serial controls, save without activation, intercepted physical connects, failure state refresh, simulation connect/disconnect, persistence, mobile layout, and no JavaScript errors.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) { const exited = new Promise(resolve => server.once('exit', resolve)); server.kill(); await exited; }
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('jochjell-hardware-ui-')) fs.rmSync(scratch, { recursive: true, force: true });
});
