/* Switch mapping and physical commands against disposable station and bridge fixtures. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-turnout-connectors-'));
let server, browser, peer, heartbeat;
let rejectCommands = false;
const commands = [];
const bridge = net.createServer(socket => {
  peer = socket; let buffer = '';
  socket.on('error', () => {}); // Restarting the disposable app can reset the fixture socket.
  const send = () => { if (!socket.destroyed) socket.write('{"contacts":[]}\n'); };
  send(); heartbeat = setInterval(send, 100);
  socket.on('close', () => clearInterval(heartbeat));
  socket.on('data', chunk => {
    buffer += chunk.toString();
    while (buffer.includes('\n')) {
      const newline = buffer.indexOf('\n'); const command = JSON.parse(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1);
      commands.push(command);
      socket.write(JSON.stringify({ type: 'turnout_ack', request_id: command.request_id, module: command.module, output: command.output, position: command.position, accepted: !rejectCommands, detail: rejectCommands ? 'Fixture switch jammed' : '' }) + '\n');
    }
  });
});
async function start() {
  const code = 'from backend.api.server import ControllerApplication, make_server; from backend.runtime import ControllerRuntime; from backend.infrastructure.simulation import SimulatedTrackSystem; from tests.test_hardware_switching import FakePhysicalTrack; import sys; ControllerRuntime.create_track=staticmethod(lambda config, **kwargs: SimulatedTrackSystem() if config["system"]=="simulation" else FakePhysicalTrack()); app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); app.stop_motion_clock(); print(server.server_port, flush=True); server.serve_forever()';
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', code, path.join(scratch, 'controller.sqlite3')], { cwd: path.resolve(__dirname, '..'), windowsHide: true });
  let errors = '';
  server.stderr.on('data', chunk => { errors += chunk; });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(errors || 'Startup timed out')), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.stdout.once('data', chunk => { clearTimeout(timer); resolve('http://127.0.0.1:' + String(chunk).trim()); });
  });
}
async function stop() {
  if (!server || server.exitCode !== null) return;
  const done = new Promise(resolve => server.once('exit', resolve)); server.kill(); await done;
}
(async () => {
  await new Promise(resolve => bridge.listen(0, '127.0.0.1', resolve));
  let url = await start();
  browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function command(payload) {
    const result = await page.request.post(url + '/api/commands', { data: payload });
    assert.ok(result.ok(), await result.text()); return result.json();
  }
  async function ready() {
    await page.goto(url + '/#settings');
    try { await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date')); }
    catch (error) { throw new Error(error.message + '\nBrowser errors: ' + errors.join('; ') + '\nSettings status: ' + await page.locator('#settings-save-status').textContent()); }
  }
  async function open() {
    await page.locator('#open-turnout-connectors').click();
    await page.waitForFunction(() => document.querySelector('#connector-save-status').textContent === 'Switch connections loaded.');
  }
  async function payload() { return (await page.request.get(url + '/api/turnout-connectors')).json(); }
  await ready(); await open();
  assert.equal(await page.locator('#connector-source').inputValue(), 'command_station');
  await page.locator('#connector-source').selectOption('computer');
  await page.locator('#connector-module').fill('2');
  await page.locator('#connector-output').fill('3');
  await page.locator('#connector-pulse').fill('400');
  await page.locator('#connector-inverted').selectOption('true');
  await page.locator('#connector-save').click();
  await page.waitForFunction(() => document.querySelector('#connector-save-status').textContent === 'Switch connection saved.');
  assert.equal(commands.length, 0, 'Saving never actuates switches');
  assert.ok(await page.locator('#connector-diverging').isDisabled(), 'Simulation never actuates physical switches');
  await page.locator('#connector-output').fill('4');
  await page.waitForTimeout(1000);
  assert.equal(await page.locator('#connector-output').inputValue(), '4', 'Polling preserves mapping draft');
  await page.locator('#connector-discard').click();
  assert.equal(await page.locator('#connector-output').inputValue(), '3');
  await page.locator('#connector-connection').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments loaded.');
  assert.equal(await page.locator('#feedback-system').inputValue(), 'computer', 'Connection shortcut chooses shared bridge');
  await page.locator('#feedback-transport').selectOption('tcp');
  await page.locator('#feedback-port').fill(String(bridge.address().port));
  await page.locator('#feedback-connection-save').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Connection settings saved.');
  await page.locator('#feedback-connect').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent.startsWith('Detectors connected.'));
  assert.equal(commands.length, 0, 'Connecting never actuates switches');
  await page.locator('[data-feedback-close]').click();
  const settings = await page.request.post(url + '/api/settings', { data: { hardware: { system: 'ecos', host: '127.0.0.1' } } });
  assert.ok(settings.ok());
  await command({ type: 'connect_hardware' });
  await ready(); await open();
  await page.locator('#connector-diverging').click();
  await page.waitForFunction(() => document.querySelector('#connector-save-status').textContent === 'Switch command accepted: diverging.');
  assert.equal(commands.length, 1);
  assert.equal(commands[0].position, 'straight', 'Inversion applies on the wire');
  assert.equal(commands[0].pulse_ms, 400);
  assert.equal((await payload()).turnouts[0].state, 'diverging');
  rejectCommands = true;
  await page.locator('#connector-straight').click();
  await page.waitForFunction(() => document.querySelector('#connector-save-status').textContent.startsWith('Switch command failed:'));
  assert.match(await page.locator('#connector-save-status').textContent(), /jammed/);
  assert.equal((await payload()).turnouts[0].state, 'diverging', 'Rejected command retains prior digital state');
  assert.equal((await payload()).computer_feedback.healthy, false);
  rejectCommands = false;
  await page.locator('#connector-straight').click();
  await page.waitForFunction(() => document.querySelector('#connector-save-status').textContent === 'Switch command accepted: straight.');
  await command({ type: 'track_power', enabled: true });
  await page.locator('#turnout-connector-close').click(); await ready(); await open();
  assert.ok(await page.locator('#connector-save').isDisabled(), 'Physical power guards mapping edits: ' + JSON.stringify(await payload()) + ' UI: ' + await page.locator('#connector-power-note').textContent());
  assert.ok(await page.locator('#connector-source').isDisabled());
  await command({ type: 'track_power', enabled: false });
  await page.locator('#turnout-connector-close').click(); await ready(); await open();
  if (process.env.SCREENSHOT_DIR) {
    fs.mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.locator('#turnout-connectors-editor').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'turnout-connectors-desktop.png') });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.locator('#turnout-connectors-editor').evaluate(node => node.scrollWidth <= node.clientWidth + 2));
  if (process.env.SCREENSHOT_DIR) await page.locator('#turnout-connectors-editor').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'turnout-connectors-mobile.png') });
  await page.locator('#turnout-connector-close').click();
  await stop(); url = await start(); await ready(); await open();
  assert.equal(await page.locator('#connector-source').inputValue(), 'computer');
  assert.equal(await page.locator('#connector-output').inputValue(), '3');
  assert.equal((await payload()).computer_feedback.connected, false);
  assert.equal((await payload()).assignments[0].confirmed_state, null);
  await page.locator('#connector-source').selectOption('command_station');
  await page.locator('#connector-save').click();
  await page.waitForFunction(() => document.querySelector('#connector-save-status').textContent === 'Switch connection saved.');
  assert.equal((await payload()).assignments.length, 0, 'Command station selection removes computer output mapping');
  assert.deepEqual(errors, []);
  console.log('PASS: switch USB/TCP mapping, shared connection, real bridge acknowledgements, inverted pulses, rejection/recovery, power guards, simulation isolation, restart, drafts and mobile.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  clearInterval(heartbeat); if (peer) peer.destroy(); await new Promise(resolve => bridge.close(resolve));
  if (browser) await browser.close(); await stop();
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-turnout-connectors-')) fs.rmSync(scratch, { recursive: true, force: true });
});
