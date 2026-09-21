/* Standalone module integration against the real DOM, CSS and settings API.
 * Does not depend on edits to app.js or index.html. Always uses a disposable DB.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const moduleApi = require('../frontend/workspace-layout.js');
const root = path.resolve(__dirname, '..');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-panel-test-'));
let server, browser;
async function start() {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c',
    'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); s=make_server(port=0, application=app); print(s.server_port, flush=True); s.serve_forever()',
    path.join(scratch, 'controller.sqlite3')], { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
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
async function mount(page, url) {
  await page.goto(`${url}/api/settings`);
  const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '');
  await page.setContent(html);
  // Relative links from /api/settings do not point to frontend assets.
  for (const file of ['styles.css', 'minimal.css', 'workspace-layout.css']) {
    if (fs.existsSync(path.join(root, 'frontend', file))) await page.addStyleTag({ path: path.join(root, 'frontend', file) });
  }
  await page.addScriptTag({ path: path.join(root, 'frontend/workspace-layout.js') });
  await page.evaluate(async () => {
    window.panelLayout = WorkspaceLayout.create(); await panelLayout.ready;
    document.querySelector('#settings-page').classList.remove('is-hidden');
    window.visitPanelPage = page => {
      document.body.dataset.workspace = page;
      document.querySelector('.sidebar').classList.toggle('is-hidden', !['dispatch', 'trains'].includes(page));
      const visible = WorkspaceLayout.defaults().pages[page].order;
      const ids = { 'layout-info': 'layout-info-panel', 'node-graph': 'layout-panel', automation: 'automation-studio-panel', systematic: 'systematic-panel', trains: 'train-panel', 'train-profile': 'train-editor-panel', 'rolling-stock': 'rolling-stock-panel', programming: 'programming-panel', calibration: 'calibration-panel', assembler: 'assembler-panel', timetable: 'timetable-panel', scans: 'scan-panel' };
      for (const [key, id] of Object.entries(ids)) document.getElementById(id).classList.toggle('is-hidden', !visible.includes(key) || key === 'systematic');
      panelLayout.setPage(page);
    };
    visitPanelPage('dispatch');
    window.originalSpeedDial = document.querySelector('#speed-slider');
  });
}
(async () => {
  assert.deepEqual(moduleApi.normalize({ pages: { dispatch: { order: ['bad'], sidebar_side: 'top' } } }), moduleApi.defaults());
  let url = await start();
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await mount(page, url);
  await page.locator('#workspace-layout-side').selectOption('right');
  await page.getByRole('button', { name: 'Move Layout information down', exact: true }).click();
  await page.getByRole('button', { name: 'Move Layout information down', exact: true }).click();
  await page.getByRole('button', { name: 'Move Layout information down', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Move Layout information down', exact: true }).isDisabled(), true);
  assert.deepEqual(await page.evaluate(() => panelLayout.getPreferences().pages.dispatch.order), ['node-graph', 'systematic', 'trains', 'timetable', 'layout-info']);
  await page.evaluate(() => visitPanelPage('dispatch'));
  const boxes = await page.evaluate(() => ['.sidebar', '.workspace', '#layout-panel', '#layout-info-panel'].map(selector => {
    const r = document.querySelector(selector).getBoundingClientRect(); return { x: r.x, y: r.y };
  }));
  assert.ok(boxes[0].x > boxes[1].x, 'Controls appear to the right');
  assert.ok(boxes[3].y > boxes[2].y, 'Information appears below graph');
  assert.equal(await page.evaluate(() => originalSpeedDial === document.querySelector('#speed-slider')), true, 'Controls retain their DOM identity');
  await page.getByRole('button', { name: 'Save arrangement', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#workspace-layout-status').textContent.includes('saved on'));
  await page.locator('#workspace-layout-page').selectOption('layout');
  await page.getByRole('button', { name: 'Move Layout information down', exact: true }).click();
  await page.getByRole('button', { name: 'Discard arrangement changes', exact: true }).click();
  assert.equal(await page.evaluate(() => panelLayout.getPreferences().pages.layout.order[0]), 'layout-info');
  await page.evaluate(() => visitPanelPage('layout'));
  assert.equal(await page.locator('#train-panel').isVisible(), false, 'Moved train panel stays hidden on layout page');
  await page.locator('#workspace-layout-page').selectOption('trains');
  await page.getByRole('button', { name: 'Move Control center down', exact: true }).click();
  await page.route('**/api/settings', route => route.request().method() === 'POST' ? route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"Unavailable"}' }) : route.continue());
  await page.getByRole('button', { name: 'Save arrangement', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#workspace-layout-status').textContent.includes('not saved'));
  assert.equal(await page.evaluate(() => panelLayout.isDirty()), true);
  await page.unroute('**/api/settings');
  await page.getByRole('button', { name: 'Save arrangement', exact: true }).click();
  await page.waitForFunction(() => !panelLayout.isDirty());
  await stop(); url = await start(); await mount(page, url);
  assert.equal(await page.evaluate(() => panelLayout.getPreferences().pages.dispatch.sidebar_side), 'right');
  assert.equal(await page.evaluate(() => panelLayout.getPreferences().pages.trains.sidebar_order[0]), 'selected-train');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'Mobile has no horizontal overflow');
  await page.getByRole('button', { name: 'Reset all pages', exact: true }).click();
  await page.getByRole('button', { name: 'Save arrangement', exact: true }).click();
  await page.waitForFunction(() => !panelLayout.isDirty());
  assert.deepEqual(await page.evaluate(() => panelLayout.getPreferences()), moduleApi.defaults());
  assert.deepEqual(errors, []);
  console.log('Workspace preference browser tests passed: order, side, identity, isolation, discard, failure, restart, mobile, reset.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close(); await stop(); fs.rmSync(scratch, { recursive: true, force: true });
});
