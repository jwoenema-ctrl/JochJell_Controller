/* Independent detector connection UI against a receive-only TCP bridge. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-computer-feedback-'));
let server, browser, peer;
let occupied = false, heartbeat, unexpectedWrites = '';
const bridge = net.createServer(socket => {
  peer = socket;
  socket.on('data', chunk => { unexpectedWrites += chunk.toString(); });
  const send = () => { if (!socket.destroyed) socket.write(JSON.stringify({ contacts: [{ module: 1, input: 1, occupied }] }) + '\n'); };
  send(); heartbeat = setInterval(send, 100);
  socket.on('close', () => clearInterval(heartbeat));
});
async function start() {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', 'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); print(server.server_port, flush=True); server.serve_forever()', path.join(scratch, 'controller.sqlite3')], { cwd: path.resolve(__dirname, '..'), windowsHide: true });
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
  async function open() {
    await page.goto(url + '/#settings');
    await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
    await page.locator('#open-feedback-mapping').click();
    await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments loaded.');
    await page.locator('#feedback-system').selectOption('computer');
    await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments loaded.');
  }
  async function payload() { return (await page.request.get(url + '/api/block-feedback?system=computer')).json(); }
  async function poll(predicate) {
    for (let i = 0; i < 60; i++) { const state = await payload(); if (predicate(state)) return state; await new Promise(resolve => setTimeout(resolve, 100)); }
    throw new Error('Detector state did not reach expectation');
  }
  await open();
  assert.ok(await page.locator('#feedback-serial-fields').isVisible());
  await page.locator('#feedback-serial-port').fill('COM7');
  await page.locator('#feedback-baudrate').fill('57600');
  assert.ok(await page.locator('#feedback-connect').isDisabled(), 'Save connection before activation');
  await page.locator('#feedback-connection-save').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Connection settings saved.');
  assert.equal((await payload()).computer_feedback.config.serial_port, 'COM7');
  assert.equal((await payload()).computer_feedback.connected, false);
  await page.locator('#feedback-transport').selectOption('tcp');
  assert.ok(await page.locator('#feedback-tcp-fields').isVisible());
  assert.ok(await page.locator('#feedback-serial-fields').isHidden());
  await page.locator('#feedback-port').fill(String(bridge.address().port));
  await page.locator('#feedback-timeout').fill('0.5');
  await page.locator('#feedback-connection-save').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Connection settings saved.');
  await page.locator('#feedback-block').selectOption('B02');
  await page.locator('#feedback-add-contact').click();
  await page.locator('[data-feedback-module]').fill('1');
  await page.locator('[data-feedback-input]').fill('1');
  await page.locator('#feedback-save').click();
  await page.waitForFunction(() => document.querySelector('#feedback-save-status').textContent === 'Assignments saved on this controller.');
  await page.locator('#feedback-connect').click();
  await poll(data => data.computer_feedback.connected && data.computer_feedback.healthy);
  assert.ok(await page.locator('#feedback-connection-save').isDisabled());
  assert.ok(await page.locator('#feedback-host').isDisabled());
  occupied = true;
  await poll(data => data.computer_feedback.occupied_blocks.B02?.includes('sensor:computer:1:1'));
  let state = await (await page.request.get(url + '/api/state')).json();
  assert.notEqual(state.layout.blocks.find(block => block.id === 'b02').status, 'occupied', 'Preview readings do not replace simulated occupancy');
  clearInterval(heartbeat);
  await poll(data => !data.computer_feedback.healthy && data.computer_feedback.occupied_blocks.B02?.[0].includes('unknown'));
  await page.waitForFunction(() => document.querySelector('#feedback-connection-status').textContent.includes('stale'));
  peer.write(JSON.stringify({ contacts: [{ module: 1, input: 1, occupied: false }] }) + '\n');
  await poll(data => data.computer_feedback.healthy);
  assert.equal(unexpectedWrites, '', 'Detector stream is receive-only');
  if (process.env.SCREENSHOT_DIR) {
    fs.mkdirSync(process.env.SCREENSHOT_DIR, { recursive: true });
    await page.locator('#block-feedback-editor').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'computer-feedback-desktop.png') });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.locator('#block-feedback-editor').evaluate(node => node.scrollWidth <= node.clientWidth + 2));
  if (process.env.SCREENSHOT_DIR) await page.locator('#block-feedback-editor').screenshot({ path: path.join(process.env.SCREENSHOT_DIR, 'computer-feedback-mobile.png') });
  await page.locator('#feedback-disconnect').click();
  await poll(data => !data.computer_feedback.connected);
  await page.locator('[data-feedback-close]').click();
  await stop(); url = await start(); await open();
  const restored = await payload();
  assert.equal(restored.computer_feedback.connected, false, 'Restart does not activate saved detector connection');
  assert.equal(restored.computer_feedback.config.port, bridge.address().port);
  assert.equal(restored.assignments[0].block_id, 'B02');
  assert.equal(await page.locator('#feedback-transport').inputValue(), 'tcp');
  await page.locator('#feedback-host').fill('draft-host');
  await page.waitForTimeout(1200);
  assert.equal(await page.locator('#feedback-host').inputValue(), 'draft-host', 'Polling retains connection drafts');
  await page.locator('#feedback-discard').click();
  assert.equal(await page.locator('#feedback-host').inputValue(), '127.0.0.1');
  const guide = await page.request.get(url + '/computer-feedback.html');
  assert.ok(guide.ok());
  assert.match(await guide.text(), /one complete snapshot per line/);
  assert.deepEqual(errors, []);
  console.log('PASS: computer detector serial/TCP settings, real receive-only bridge, fresh/stale protection, simulation preview, reconnect persistence, drafts and mobile layout.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  clearInterval(heartbeat); if (peer) peer.destroy();
  await new Promise(resolve => bridge.close(resolve));
  if (browser) await browser.close(); await stop();
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-computer-feedback-')) fs.rmSync(scratch, { recursive: true, force: true });
});
