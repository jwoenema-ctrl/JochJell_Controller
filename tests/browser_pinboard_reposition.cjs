/* Real pointer gestures against disposable simulation and station fixtures. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-pinboard-drag-'));
let server, browser;
async function start() {
  const code = [
    'from backend.api.server import ControllerApplication, make_server',
    'from backend.runtime import ControllerRuntime',
    'from backend.infrastructure.simulation import SimulatedTrackSystem',
    'from tests.test_hardware_switching import FakePhysicalTrack',
    'import sys',
    'ControllerRuntime.create_track=staticmethod(lambda config, **kwargs: SimulatedTrackSystem() if config["system"]=="simulation" else FakePhysicalTrack())',
    'app=ControllerApplication.sample(database_path=sys.argv[1])',
    'app.command({"type":"set_mode","mode":"stopped"})',
    'app.command({"type":"update_train","train_id":"t1","train":{"length_mm":80}})',
    'app.command({"type":"update_train","train_id":"t2","train":{"length_mm":80}})',
    'app.runtime.train_database.add_calibration("train-101",speed_kmh=10,duration_ms=100,measured_distance_mm=50,created_at="2026-01-01T00:00:00Z")',
    'server=make_server(port=0,application=app)',
    'app.stop_motion_clock()',
    'print(server.server_port,flush=True)',
    'server.serve_forever()'
  ].join('; ');
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', code, path.join(scratch, 'controller.sqlite3')], { cwd: path.resolve(__dirname, '..'), windowsHide: true });
  let errors = ''; server.stderr.on('data', data => { errors += data; });
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
(async () => {
  const url = await start();
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  const commands = [];
  page.on('request', request => { if (request.url().endsWith('/api/commands') && request.method() === 'POST') commands.push(request.postDataJSON()); });
  async function command(data) { const response = await page.request.post(url + '/api/commands', { data }); assert.ok(response.ok(), await response.text()); return response.json(); }
  async function state() { return (await page.request.get(url + '/api/state')).json(); }
  async function targetPoint(x, y) {
    return page.locator('#layout-svg').evaluate((svg, target) => {
      const point = svg.createSVGPoint(); point.x = target.x; point.y = target.y;
      const screen = point.matrixTransform(svg.getScreenCTM()); return { x: screen.x, y: screen.y };
    }, { x, y });
  }
  async function drag(id, x, y, { shift = false, releaseEarly = false, cancel = false, pauseBeforeDrop = false } = {}) {
    const body = page.locator(`[data-pinboard-train-id="${id}"] .pinboard-vehicle`).first();
    // Polling replaces SVG groups; scroll the stable canvas container instead.
    await page.locator('#map-stage').scrollIntoViewIfNeeded();
    const box = await body.boundingBox(); assert.ok(box);
    const target = await targetPoint(x, y);
    if (shift) await page.keyboard.down('Shift');
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x, target.y, { steps: 5 });
    if (pauseBeforeDrop) {
      await page.waitForTimeout(1200);
      assert.equal(await page.locator('.pinboard-train.is-dragging').count(), 1, 'Polling keeps the grabbed element');
      assert.equal(await page.locator('#pinboard-drag-preview').getAttribute('visibility'), 'visible');
    }
    if (shift || id === 'wagon') assert.equal(await page.locator('#pinboard-drag-preview text').textContent(), 'PLACE');
    else assert.equal(await page.locator('#pinboard-drag-preview text').textContent(), 'DEST');
    if (releaseEarly) await page.keyboard.up('Shift');
    if (cancel) await page.locator('#layout-svg').dispatchEvent('pointercancel', { pointerId: 1 });
    await page.mouse.up();
    if (shift && !releaseEarly) await page.keyboard.up('Shift');
  }
  await page.goto(url + '/#dispatch');
  await page.waitForFunction(() => document.querySelector('#block-count').textContent === '4');
  await page.locator('[data-layout-view="pinboard"]').click();
  await command({ type: 'add_train', train: { id: 'wagon', name: 'Loose wagon', address: null, mode: 'stopped', speed: 0,
    block_id: 'B04', length_mm: 160, consist: [{ id: 'wagon-body', name: 'Loose wagon', type: 'freight_wagon', length_mm: 160 }] } });
  await page.locator('[data-pinboard-train-id="wagon"]').waitFor();
  assert.equal(await page.locator('[data-pinboard-train-id="wagon"] .is-locomotive').count(), 0);
  commands.length = 0;
  await drag('wagon', 560, 178);
  await page.waitForFunction(async () => (await fetch('/api/state').then(r => r.json())).trains.find(t => t.id === 'wagon').position === 'B02');
  assert.deepEqual(commands.map(c => c.type), ['reposition_train_on_track'], 'Loose rolling stock never asks for calibrated movement');
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="wagon"]').dataset.anchorX) > 550);
  commands.length = 0;
  await drag('wagon', 610, 178, { shift: true });
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="wagon"]').dataset.anchorX) > 600);
  assert.deepEqual(commands.map(c => c.type), ['reposition_train_on_track']);
  await command({ type: 'set_train_graph_membership', train_id: 'wagon', enabled: false });
  await page.locator('[data-pinboard-train-id="wagon"]').waitFor({ state: 'detached' });
  await command({ type: 'set_train_mode', train_id: 't2', mode: 'manual' });
  commands.length = 0;
  await drag('t2', 560, 178);
  await page.waitForFunction(() => document.querySelector('#toast-region').textContent.includes('calibration measurement'));
  assert.deepEqual(commands.map(c => c.type), ['move_train_to_coordinate']);
  commands.length = 0;
  await drag('t2', 560, 178, { shift: true });
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="t2"]').dataset.anchorX) > 550);
  assert.deepEqual(commands.map(c => c.type), ['reposition_train_on_track'], 'Shift bypasses calibration and execution');
  commands.length = 0;
  await drag('t2', 640, 178, { shift: true, releaseEarly: true, pauseBeforeDrop: true });
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="t2"]').dataset.anchorX) > 630);
  assert.deepEqual(commands.map(c => c.type), ['reposition_train_on_track'], 'Releasing Shift before drop cannot accidentally drive');
  commands.length = 0;
  await drag('t2', 600, 178, { shift: true, cancel: true });
  assert.deepEqual(commands, [], 'Cancelled gesture never sends placement or drive');
  assert.equal(await page.locator('.pinboard-train.is-dragging').count(), 0);
  commands.length = 0;
  await drag('t2', 900, 340, { shift: true });
  assert.deepEqual(commands, [], 'Off-track drop never sends a command');
  await command({ type: 'set_train_graph_membership', train_id: 't2', enabled: false });
  await command({ type: 'set_train_mode', train_id: 't1', mode: 'manual' });
  await page.reload(); await page.waitForFunction(() => document.querySelector('#block-count').textContent === '4');
  await page.locator('[data-layout-view="pinboard"]').click();
  commands.length = 0;
  const targetResponse = page.waitForResponse(response => response.url().endsWith('/api/commands') && response.request().postDataJSON()?.type === 'move_train_to_coordinate');
  const executionResponse = page.waitForResponse(response => response.url().endsWith('/api/commands') && response.request().postDataJSON()?.type === 'execute_coordinate_move');
  await drag('t1', 350, 178);
  const targetResult = await targetResponse;
  assert.ok(targetResult.ok(), await targetResult.text());
  const executionResult = await executionResponse;
  assert.ok(executionResult.ok(), await executionResult.text());
  assert.equal((await executionResult.json()).coordinate_execution.state, 'running');
  assert.deepEqual(commands.map(c => c.type), ['move_train_to_coordinate', 'execute_coordinate_move'], 'Ordinary calibrated dragging still drives');
  await command({ type: 'stop_train', train_id: 't1' });
  const settings = await page.request.post(url + '/api/settings', { data: { hardware: { system: 'ecos', host: '127.0.0.1' } } });
  assert.ok(settings.ok(), await settings.text());
  await command({ type: 'connect_hardware' });
  await command({ type: 'reposition_train_on_track', train_id: 't2', x: 560, y: 178 });
  await page.waitForFunction(() => !!document.querySelector('[data-pinboard-train-id="t2"]'));
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="t2"]').dataset.anchorX) > 550);
  commands.length = 0;
  await drag('t2', 650, 178, { shift: true });
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="t2"]').dataset.anchorX) > 640);
  assert.deepEqual(commands.map(c => c.type), ['reposition_train_on_track']);
  const hardware = await state(); const train = hardware.trains.find(t => t.id === 't2');
  assert.equal(hardware.simulation_mode, false);
  assert.equal(train.pinboard_position.source, 'manual');
  assert.equal(train.position, '—', 'Graphic placement does not invent identified hardware position');
  assert.equal(train.speed, 0);
  assert.equal(hardware.track_power, false);
  await page.reload(); await page.waitForFunction(() => document.querySelector('#block-count').textContent === '4');
  await page.locator('[data-layout-view="pinboard"]').click();
  await page.waitForFunction(() => Number(document.querySelector('[data-pinboard-train-id="t2"]')?.dataset.anchorX) > 640);
  assert.deepEqual(errors, []);
  console.log('PASS: wagon dragging, Shift placement, early Shift release, cancellation, invalid drops, normal calibrated driving and hardware visual-only placement across browser reload.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  await stop(); if (browser) await browser.close();
  const resolved = path.resolve(scratch);
  if (path.dirname(resolved) === path.resolve(os.tmpdir()) && path.basename(resolved).startsWith('h0-pinboard-drag-')) fs.rmSync(resolved, { recursive: true, force: true });
});
