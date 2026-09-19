/* Focused assembler/inventory integration test. Uses simulation only. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '..');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-assembler-test-'));
let server;
let browser;

async function startServer() {
  const code = 'from backend.api.server import ControllerApplication, make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); server=make_server(port=0, application=app); print(server.server_port, flush=True); server.serve_forever()';
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', code, path.join(scratch, 'controller.sqlite3')], {
    cwd: root,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let errors = '';
  server.stderr.on('data', data => { errors += data; });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(errors || 'Test server did not start')), 15000);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', codeValue => { clearTimeout(timer); if (codeValue) reject(new Error(errors || `Server exited ${codeValue}`)); });
    server.stdout.once('data', data => { clearTimeout(timer); resolve(`http://127.0.0.1:${String(data).trim()}`); });
  });
}

async function stopServer() {
  if (!server || server.exitCode !== null) return;
  const exited = new Promise(resolve => server.once('exit', resolve));
  server.kill();
  await exited;
}

(async () => {
  const url = await startServer();
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  const commands = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().endsWith('/api/commands') && request.method() === 'POST') commands.push(request.postDataJSON());
  });

  await page.request.post(`${url}/api/commands`, { data: {
    type: 'upsert_rolling_stock_inventory',
    item_id: 'persisted-test-coach',
    name: 'Persisted test coach',
    vehicle_type: 'coach',
    quantity: 3,
    manufacturer: 'Test Works',
    model: 'TW-310',
    length_mm: 310,
    mass_g: 42000,
  } });

  await page.goto(`${url}/#trains`);
  await page.waitForFunction(() => document.querySelector('#sync-message').textContent.includes('online'));
  await page.getByRole('link', { name: 'Assembler', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#assembler-panel').classList.contains('is-hidden') === false);

  const options = await page.locator('#rolling-stock-select option').allTextContents();
  assert.deepEqual(options, ['Persisted test coach · coach · ×3'], 'Assembler must use persistent inventory entries');
  assert.equal(await page.locator('#rolling-stock-select').isDisabled(), false);

  await page.locator('#assembler-train-select').selectOption('t1');
  await page.locator('#rolling-stock-select').selectOption('persisted-test-coach');
  await page.locator('#add-car').click();
  assert.match(await page.locator('#consist-list').textContent(), /Persisted test coach/);
  const saveRequest = page.waitForRequest(request => request.url().endsWith('/api/commands') && request.postDataJSON()?.type === 'update_consist');
  await page.locator('#save-consist').click();
  await saveRequest;

  const consistCommand = commands.find(command => command.type === 'update_consist');
  assert.ok(consistCommand, 'Assembler must persist the updated consist');
  assert.equal(consistCommand.consist.at(-1).catalogue_id, 'persisted-test-coach');
  assert.equal(consistCommand.consist.at(-1).length_mm, 310);
  assert.equal(consistCommand.consist.at(-1).mass_g, 42000);
  assert.deepEqual(errors, []);
  console.log('PASS: assembler reads persistent rolling-stock inventory and saves normalized catalogue metadata.');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stopServer();
  if (path.dirname(scratch) === path.resolve(os.tmpdir()) && path.basename(scratch).startsWith('h0-assembler-test-')) fs.rmSync(scratch, { recursive: true, force: true });
});