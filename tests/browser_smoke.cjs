/* Isolated browser integration check. Never connects to physical Z21 hardware. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-ui-test-'));
const database = path.join(scratch, 'controller.sqlite3');
const screenshots = process.env.SCREENSHOT_DIR;
const python = process.env.PYTHON || 'python';
let server;
let browser;

async function startServer() {
  const code = 'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); print(server.server_port, flush=True); server.serve_forever()';
  server = spawn(python, ['-u', '-c', code, database], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let errors = '';
  server.stderr.on('data', data => { errors += data; });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Test server did not start: ${errors}`)), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); if (code) reject(new Error(errors)); });
    server.stdout.once('data', data => { clearTimeout(timer); resolve(`http://127.0.0.1:${String(data).trim()}`); });
  });
}

async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise(resolve => server.once('exit', resolve));
  server.kill();
  await exited;
}

async function shot(page, name) {
  if (screenshots) {
    fs.mkdirSync(screenshots, { recursive: true });
    await page.screenshot({ path: path.join(screenshots, `${name}.png`), fullPage: true });
  }
}

(async () => {
  let url = await startServer();
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'light' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('#sync-message').textContent.includes('online'));
  assert.equal(await page.locator('#direction-reverse').isDisabled(), true, 'Automatic train direction is locked');
  await page.locator('.train-row').filter({ hasText: 'ICE 3' }).click();
  await page.locator('#direction-reverse').click();
  await page.waitForFunction(() => document.querySelector('#direction-reverse').getAttribute('aria-pressed') === 'true');
  assert.equal(await page.locator('#speed-readout').textContent(), '0');
  await page.locator('#direction-forward').click();
  await page.waitForFunction(() => document.querySelector('#direction-forward').getAttribute('aria-pressed') === 'true');
  await page.getByRole('link', { name: 'Locomotives', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#train-panel').classList.contains('is-hidden') === false);
  await page.waitForFunction(() => {
    const navigation = document.querySelector('.trains-subnav')?.getBoundingClientRect();
    const panel = document.querySelector('#train-panel')?.getBoundingClientRect();
    return navigation && panel && panel.top >= navigation.bottom - 1;
  });
  assert.equal(await page.locator('.trains-subnav').evaluate(node => getComputedStyle(node).position), 'sticky', 'Train navigation should stay above its selected panel');
  assert.equal(await page.locator('#train-panel .panel-heading h2').textContent(), 'Locomotives');
  assert.ok(await page.locator('.train-row').count() >= 1, 'Locomotive subcategory must show locomotive records');
  assert.match(await page.locator('.train-row').first().textContent(), /→|#/, 'Locomotive rows show service data');
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#train-panel .panel-heading h2').textContent === 'Train overview');
  assert.match(await page.locator('.train-row').filter({ hasText: 'ICE 3' }).textContent(), /Central station/, 'Train overview must show the next scheduled destination');
  await page.getByRole('link', { name: 'Programming', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#programming-panel').classList.contains('is-hidden') === false);
  await page.locator('#programming-new-address').fill('7');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#program-dcc-address').click();
  await page.waitForFunction(() => document.querySelector('#programming-status').textContent.includes('DCC address 3 → 7'));
  const programmedState = await (await page.request.get(`${url}/api/state`)).json();
  assert.equal(programmedState.trains.find(train => train.id === 't2').number, '7', 'Programming must persist a new DCC address');
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#train-panel .panel-heading h2').textContent === 'Train overview');
  await page.getByRole('button', { name: 'Settings', exact: true }).first().click();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  assert.equal(await page.locator('.dashboard').isVisible(), false, 'Settings must be a distinct page');
  assert.equal(await page.locator('#settings-page').isVisible(), true);
  await shot(page, 'settings-light');
  await page.locator('#setting-theme').selectOption('dark');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark', 'Theme must preview instantly');
  await page.locator('#setting-z21-host').fill('192.168.0.120');
  await page.locator('#setting-ui-refresh').fill('2');
  await page.locator('#setting-routing-busy').fill('0.5');
  await page.locator('#setting-routing-idle').fill('3');
  await page.locator('#settings-save').click();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent === 'Saved on this controller.');
  let settings = await (await page.request.get(`${url}/api/settings`)).json();
  assert.equal(settings.settings.z21_host, '192.168.0.120');
  assert.equal(settings.settings.routing.busy_interval_ms, 500);
  assert.equal(settings.settings.routing.idle_interval_ms, 3000);
  assert.equal(settings.settings.ui_refresh_ms, 2000);
  assert.equal((await (await page.request.get(`${url}/api/connection`)).json()).simulated, true, 'Saving must not enable physical mode');
  await shot(page, 'settings-dark');
  await page.locator('#setting-theme').selectOption('light');
  await page.locator('#settings-discard').click();
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark', 'Discard must restore saved theme');
  await page.locator('#setting-z21-host').fill('not-an-ip');
  await page.locator('#settings-save').click();
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.startsWith('Not saved:'));
  await page.locator('#settings-discard').click();

  // Generate a small test photo locally; no user files or external image sources.
  const photo = await page.evaluate(() => { const c = document.createElement('canvas'); c.width = 320; c.height = 180; const g = c.getContext('2d'); g.fillStyle = '#608878'; g.fillRect(0,0,320,180); g.strokeStyle = '#eee'; g.lineWidth = 8; g.strokeRect(35,35,250,110); return c.toDataURL('image/png').split(',')[1]; });
  await page.locator('#settings-scan-file').setInputFiles({ name: 'test-layout.png', mimeType: 'image/png', buffer: Buffer.from(photo, 'base64') });
  await page.locator('#settings-upload-scan').click();
  await page.waitForFunction(() => document.querySelector('#settings-upload-status').textContent.startsWith('Photo saved'));
  await page.locator('#settings-scan-library [data-view-scan]').last().click();
  await page.locator('#scan-viewer-host canvas').waitFor({ state: 'visible' });
  await page.waitForTimeout(400);
  const initialHeight = await page.evaluate(() => document.documentElement.scrollHeight);
  const heights = [];
  for (let n = 0; n < 20; n++) {
    await page.evaluate(() => window.dispatchEvent(new Event('resize')));
    await page.waitForTimeout(30);
    heights.push(await page.evaluate(() => document.documentElement.scrollHeight));
  }
  assert.ok(heights.every(height => Math.abs(height - initialHeight) <= 2), `Viewer grew: ${initialHeight} → ${heights.join(',')}`);
  const host = await page.locator('#scan-viewer-host').boundingBox();
  assert.ok(host.height >= 250 && host.height <= 600, `Unbounded viewport height ${host.height}`);
  assert.equal(await page.locator('#layout-panel').isVisible(), false, 'Scans should not show the dispatch panels');
  await shot(page, 'scans-desktop');
  for (const name of ['Home', 'Automation', 'Trains']) {
    await page.locator('.mode-nav').getByRole('button', { name, exact: true }).click();
    assert.equal(await page.locator('#settings-page').isVisible(), false);
  }
  await page.locator('.mode-nav').getByRole('button', { name: 'Settings', exact: true }).click();
  assert.equal(await page.locator('#settings-page').isVisible(), true);
  await page.locator('.mode-nav').getByRole('button', { name: 'Automation', exact: true }).click();
  await page.getByRole('button', { name: 'Systematic track', exact: true }).click();
  assert.equal(await page.locator('#systematic-panel').isVisible(), true);
  await page.getByRole('button', { name: 'Node graph', exact: true }).click();
  assert.equal(await page.locator('#map-stage').isVisible(), true);
  await page.locator('.mode-nav').getByRole('button', { name: 'Home', exact: true }).click();
  await shot(page, 'dispatch-desktop');
  assert.equal(await page.locator('#layout-panel').evaluate(node => node.classList.contains('is-editing')), false, 'Home must not leave layout dragging enabled');
  const graphBounds = await page.locator('#map-stage').boundingBox();
  for (const block of await page.locator('#layout-svg .block-node rect').all()) {
    const bounds = await block.boundingBox();
    assert.ok(bounds.y >= graphBounds.y && bounds.y + bounds.height <= graphBounds.y + graphBounds.height, 'Fit layout must include every block');
  }
  const listWidth = (await page.locator('#train-list').boundingBox()).width;
  assert.ok((await page.locator('.train-row').first().boundingBox()).width >= listWidth - 2, 'Train rows should fill the list');
  await page.locator('.mode-nav').getByRole('button', { name: 'Trains', exact: true }).click();
  await shot(page, 'trains-desktop');
  await page.locator('.mode-nav').getByRole('button', { name: 'Settings', exact: true }).click();
  await page.locator('#setting-theme').selectOption('light');
  await page.locator('.mode-nav').getByRole('button', { name: 'Home', exact: true }).click();
  await shot(page, 'dispatch-light');
  await page.locator('.mode-nav').getByRole('button', { name: 'Settings', exact: true }).click();
  await page.locator('#settings-discard').click();
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of ['Settings', 'Home', 'Trains', 'Automation']) {
    await page.locator('.mode-nav').getByRole('button', { name, exact: true }).click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 2, `${name} page overflows mobile viewport by ${overflow}px`);
    if (name === 'Settings') await shot(page, 'settings-mobile');
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('.mode-nav').getByRole('button', { name: 'Automation', exact: true }).click();
  assert.equal(await page.locator('#route-panel').isVisible(), true, 'Automation should expose saved route plans');
  assert.equal(await page.locator('#scan-panel').isVisible(), true, 'Automation should expose the 3D track viewer');
  await page.locator('#scan-viewer-host canvas').waitFor({ state: 'visible' });
  await page.locator('#new-route').click();
  await page.locator('#route-id').fill('smoke-route');
  await page.locator('#route-name').fill('Smoke route');
  await page.locator('#route-node-catalogue [data-route-palette-value="B01"]').click();
  await page.locator('#route-node-catalogue [data-route-palette-value="B04"]').click();
  await page.locator('#save-route').click();
  await page.waitForFunction(() => document.querySelector('#route-list').textContent.includes('Smoke route'));
  await page.locator('#route-list [data-route-id="smoke-route"] [data-route-action="edit"]').click();
  await page.locator('#route-name').fill('Smoke route updated');
  await page.locator('#save-route').click();
  await page.waitForFunction(() => document.querySelector('#route-list').textContent.includes('Smoke route updated'));
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#route-list [data-route-id="smoke-route"] [data-route-action="delete"]').click();
  await page.waitForFunction(() => !document.querySelector('#route-list').textContent.includes('Smoke route updated'));
  await page.getByRole('button', { name: 'Edit layout', exact: true }).click();
  assert.equal(await page.locator('#layout-info-panel').isVisible(), true);
  assert.match(await page.locator('#layout-info-metrics').textContent(), /Not measured in simulation/);
  await page.getByRole('button', { name: '2D pinboard', exact: true }).click();
  assert.equal(await page.locator('#graph-editor-tools').isVisible(), true, 'Pinboard editing should expose graph connections');
  await page.locator('#add-layout-block').click();
  await page.waitForFunction(() => document.querySelector('#block-count').textContent === '5');
  const pinboardBounds = await page.locator('#map-stage').boundingBox();
  await page.mouse.click(pinboardBounds.x + pinboardBounds.width * 0.78, pinboardBounds.y + pinboardBounds.height * 0.72);
  await page.waitForFunction(async () => {
    const state = await fetch('/api/state').then(response => response.json());
    const block = state.layout.blocks.find(item => item.id === 'b05');
    return block && Number(block.x) > 0 && Number(block.y) > 0 && (Number(block.x) !== 702 || Number(block.y) !== 224);
  });
  await page.locator('#connection-from').selectOption('b02');
  await page.locator('#connection-to').selectOption('b03');
  await page.locator('#add-spline-point').click();
  await page.waitForFunction(() => document.querySelector('#layout-svg [data-waypoint-id="WP02"]') !== null);
  await page.mouse.click(pinboardBounds.x + pinboardBounds.width * 0.52, pinboardBounds.y + pinboardBounds.height * 0.58);
  await page.waitForFunction(async () => {
    const state = await fetch('/api/state').then(response => response.json());
    const waypoint = state.layout.waypoints.find(item => item.id === 'WP02');
    return waypoint && Number(waypoint.y) > 0;
  });
  const waypointBefore = await page.evaluate(async () => {
    const state = await fetch('/api/state').then(response => response.json());
    const waypoint = state.layout.waypoints.find(item => item.id === 'WP02');
    return { x: Number(waypoint.x), y: Number(waypoint.y) };
  });
  const splineHandle = page.locator('#layout-svg [data-waypoint-id="WP02"]');
  const splineBox = await splineHandle.boundingBox();
  assert.ok(splineBox, 'Placed spline handle should be visible');
  await page.mouse.move(splineBox.x + splineBox.width / 2, splineBox.y + splineBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(splineBox.x + splineBox.width / 2 + 26, splineBox.y + splineBox.height / 2 + 18, { steps: 2 });
  await page.mouse.up();
  await page.waitForFunction(async (before) => {
    const state = await fetch('/api/state').then(response => response.json());
    const waypoint = state.layout.waypoints.find(item => item.id === 'WP02');
    return waypoint && (Number(waypoint.x) !== before.x || Number(waypoint.y) !== before.y);
  }, waypointBefore);
  assert.ok(await page.locator('#layout-svg .pinboard-rail').evaluateAll(paths => paths.some(path => String(path.getAttribute('d') || '').includes('C'))), 'Spline control point should render a curved rail');
  await page.getByRole('button', { name: 'Node graph', exact: true }).click();
  const movableBlock = page.locator('#layout-svg .block-node[data-block-id="b05"]');
  const movableBefore = await (await page.request.get(`${url}/api/state`)).json();
  const movablePoint = await movableBlock.boundingBox();
  await page.mouse.move(movablePoint.x + movablePoint.width / 2, movablePoint.y + movablePoint.height / 2);
  await page.mouse.down();
  await page.mouse.move(movablePoint.x + movablePoint.width / 2 + 34, movablePoint.y + movablePoint.height / 2 + 22, { steps: 3 });
  await page.mouse.up();
  await page.waitForFunction(async (before) => {
    const state = await fetch('/api/state').then(response => response.json());
    const block = state.layout.blocks.find(item => item.id === 'b05');
    const previous = before.layout.blocks.find(item => item.id === 'b05');
    return block && previous && (Number(block.x) !== Number(previous.x) || Number(block.y) !== Number(previous.y));
  }, movableBefore);
  await movableBlock.click();
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#delete-selected-block').click();
  await page.waitForFunction(async () => {
    const state = await fetch('/api/state').then(response => response.json());
    return state.layout.blocks.length === 4 && !state.layout.blocks.some(item => item.id === 'b05');
  });
  await page.getByRole('button', { name: '2D pinboard', exact: true }).click();
  const pinboardTrain = page.locator('#layout-svg .pinboard-train').first();
  assert.ok(await pinboardTrain.count(), 'Pinboard should render an active train marker');
  assert.equal(await page.locator('#pinboard-placement-tools').isVisible(), true, 'Pinboard should expose train placement controls');
  assert.ok(await page.locator('#pinboard-train-select optgroup').count() >= 2, 'Pinboard selector should expose trains and locomotives');
  const pinboardVehicle = pinboardTrain.locator('.pinboard-vehicle').first();
  const pinboardBox = await pinboardVehicle.boundingBox();
  assert.ok(pinboardBox, 'Pinboard train marker should have a visible vehicle bounding box');
  await page.mouse.move(pinboardBox.x + pinboardBox.width / 2, pinboardBox.y + pinboardBox.height / 2);
  assert.equal(await page.locator('#layout-svg .pinboard-train').first().locator('.pinboard-vehicle').first().evaluate(node => getComputedStyle(node).strokeWidth), '2.5px', 'Hovering a train should highlight its vehicles');
  await page.locator('.mode-nav').getByRole('button', { name: 'Trains', exact: true }).click();
  await page.locator('.trains-subnav-link[data-train-section="assembler"]').click();
  await page.waitForFunction(() => document.querySelector('#assembler-panel').classList.contains('is-hidden') === false);
  assert.equal(await page.locator('#assembler-functions').count(), 0, 'Assembler should not render the decoder function grid');
  assert.equal(await page.locator('#assembler-locomotive-select').count(), 1, 'Assembler should expose locomotive pairing');
  await page.locator('#assembler-train-select').selectOption('t1');
  await page.locator('#assembler-locomotive-select').selectOption('t2');
  await page.locator('#add-locomotive').click();
  await page.waitForFunction(() => document.querySelector('#assembler-locomotive-list').textContent.includes('ICE 3'));
  await page.locator('#save-consist').click();
  await page.waitForFunction(async () => {
    const state = await fetch('/api/state').then(response => response.json());
    return state.trains.find(train => train.id === 't1').locomotive_ids.includes('t2');
  });
  await page.request.post(`${url}/api/commands`, { data: { type: 'update_decoder_function', train_id: 't2', function: { function_number: 2, name: 'Horn', description: 'Long horn', momentary: true, enabled: true } } });
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#sync-message').textContent.includes('online'));
  await page.locator('.mode-tab[data-workspace="dispatch"]').click();
  await page.waitForFunction(() => document.querySelector('.sidebar').classList.contains('is-hidden') === false);
  await page.locator('.train-row').filter({ hasText: 'ICE 3' }).click();
  await page.waitForFunction(() => document.querySelectorAll('#selected-train-functions .train-function-button').length === 1);
  assert.match(await page.locator('#selected-train-functions').textContent(), /F2|Horn/, 'Selected train panel should show assigned decoder functions only');
  await page.locator('#selected-train-functions .train-function-button').click();
  await page.waitForFunction(async () => { const state = await fetch('/api/state').then(response => response.json()); return state.trains.find(train => train.id === 't2').decoder_function_states['2'] === true; });
  await page.locator('.mode-nav').getByRole('button', { name: 'Trains', exact: true }).click();
  await page.locator('.train-row').filter({ hasText: 'ICE 3' }).click();
  await page.locator('.editor-tab[data-editor-tab="settings"]').click();
  await page.locator('#editor-length').fill('1523.75');
  await page.locator('#save-train-settings').click();
  await page.locator('.editor-tab[data-editor-tab="datasheet"]').click();
  await page.waitForFunction(() => document.querySelector('.data-sheet').textContent.includes('1523.75 mm'));
  await page.locator('.mode-tab[data-workspace="layout"]').click();
  await page.waitForFunction(() => document.querySelector('#layout-info-panel').classList.contains('is-hidden') === false);
  await page.locator('#layout-power-toggle').click();
  await page.waitForFunction(() => document.querySelector('#layout-power-toggle').textContent === 'Power on');
  await page.locator('#edit-selected-block').click();
  await page.locator('#block-id').fill('TEST-YARD');
  await page.locator('#block-editor button[type="submit"]').click();
  await page.waitForFunction(() => !document.querySelector('#block-editor').open);
  let layoutState = await (await page.request.get(url + '/api/state')).json();
  assert.ok(JSON.stringify(layoutState).includes('test-yard'));
  assert.equal(await page.locator('#route-count').textContent(), '0');
  await page.locator('.mode-tab[data-workspace="layout"]').click();
  await page.waitForFunction(() => document.querySelector('#automation-studio-panel').classList.contains('is-hidden') === false);
  assert.equal(await page.locator('#automation-catalogue [data-action-block]').count(), 5, 'Automation catalogue should expose five train action blocks');
  await page.locator('#automation-catalogue [data-action-block="drive"]').click();
  await page.locator('#automation-catalogue [data-action-block="function"]').click();
  await page.locator('[data-automation-field="speed_kmh"]').fill('10');
  await page.locator('[data-automation-field="speed_kmh"]').press('Tab');
  await page.locator('#automation-program-name').fill('Smoke routine');
  await page.locator('#automation-save-program').click();
  await page.waitForFunction(() => document.querySelector('#automation-program-list').textContent.includes('Smoke routine'));
  const automationState = await (await page.request.get(url + '/api/state')).json();
  assert.equal(automationState.automationPrograms.length, 1, 'Automation program should be saved through the API');
  await page.request.post(`${url}/api/commands`, { data: { type: 'delete_automation_program', program_id: automationState.automationPrograms[0].id } });
  await page.waitForFunction(async () => (await fetch('/api/state').then(response => response.json())).automationPrograms.length === 0);
  await shot(page, 'layout-info-dark');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth) <= 2);
  await shot(page, 'layout-info-mobile');
  await stopServer();
  url = await startServer();
  await page.goto(`${url}/#settings`);
  await page.waitForFunction(() => document.querySelector('#settings-save-status').textContent.includes('up to date'));
  assert.equal(await page.locator('#setting-z21-host').inputValue(), '192.168.0.120', 'Saved settings must survive server restart');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  assert.equal(await page.locator('#settings-scan-library [data-view-scan]').count(), 1, 'Photo manifest must survive server restart');
  await page.locator('#settings-scan-library [data-view-scan]').click();
  await page.locator('#scan-viewer-host canvas').waitFor({ state: 'visible' });
  assert.deepEqual(errors, [], 'Browser errors');
  console.log('PASS: settings, validation, persistence across restart, photo upload, bounded 3D viewer, navigation, themes, mobile layouts, no browser errors.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stopServer();
  // Only remove this test process\'s uniquely generated temporary data.
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-ui-test-')) fs.rmSync(scratch, { recursive: true, force: true });
});
