/* Integrated panel preferences and logo verification, disposable simulation only. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'h0-goal-'));
let server, browser;
(async () => {
  server = spawn(process.env.PYTHON || 'python', ['-u', '-c', 'from backend.api.server import ControllerApplication,make_server; import sys; app=ControllerApplication.sample(database_path=sys.argv[1]); s=make_server(port=0,application=app); print(s.server_port,flush=True); s.serve_forever()', path.join(scratch,'db.sqlite3')], {cwd:path.resolve(__dirname,'..'),windowsHide:true});
  const port = await new Promise((resolve,reject) => { server.stdout.once('data',data=>resolve(String(data).trim())); server.once('error',reject); server.once('exit',code=>reject(new Error('Server exited '+code))); });
  browser = await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'chrome'});
  const page = await browser.newPage({viewport:{width:1500,height:1050}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  const nav = name=>page.locator('.mode-nav').getByRole('button',{name,exact:true}).click();
  await page.goto('http://127.0.0.1:'+port);
  await page.waitForFunction(()=>document.querySelector('#sync-message').textContent.includes('online'));
  await nav('Settings');
  await page.waitForFunction(()=>document.querySelector('#workspace-layout-status')?.textContent.includes('up to date'));
  await page.locator('#workspace-layout-page').selectOption('dispatch');
  await page.locator('#workspace-layout-side').selectOption('right');
  for(let i=0;i<3;i++) await page.getByRole('button',{name:'Move Layout information down',exact:true}).click();
  await page.getByRole('button',{name:'Save arrangement',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#workspace-layout-status').textContent.includes('saved on'));
  await nav('Home');
  async function verifyPosition(){
    const graph=await page.locator('#layout-panel').boundingBox(), info=await page.locator('#layout-info-panel').boundingBox(), sidebar=await page.locator('.sidebar').boundingBox();
    assert.ok(info.y>graph.y,'Information is below graph');
    assert.ok(sidebar.x>graph.x,'Controls are right of graph');
    assert.equal(await page.locator('#train-list').isVisible(),true);
  }
  await verifyPosition();
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#sync-message').textContent.includes('online'));
  await verifyPosition();
  const logo = page.locator('.brand-logo img');
  assert.ok(await logo.evaluate(n=>n.complete&&n.naturalWidth>0));
  assert.ok(await logo.evaluate(n=>{
    const c=document.createElement('canvas');c.width=n.naturalWidth;c.height=n.naturalHeight;
    const ctx=c.getContext('2d');ctx.drawImage(n,0,0);const data=ctx.getImageData(0,0,c.width,c.height).data;
    let clear=0;for(let i=3;i<data.length;i+=4)if(data[i]===0)clear++;return clear>10000;
  }),'Logo has actual alpha transparency');
  if(process.env.SCREENSHOT_DIR){
    fs.mkdirSync(process.env.SCREENSHOT_DIR,{recursive:true});
    await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'custom-workspace.png'),fullPage:true});
    await nav('Settings');
    await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,'custom-settings.png'),fullPage:true});
  }
  await page.setViewportSize({width:390,height:844});
  for(const name of ['Home','Automation','Trains','Settings']){
    await nav(name);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)<=2,name+' mobile overflow');
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: integrated arrangement reorder/right-side/reload, controls retained, supplied transparent logo, all mobile pages.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();
  if(server&&server.exitCode===null){const ended=new Promise(r=>server.once('exit',r));server.kill();await ended;}
  if(path.dirname(scratch)===path.resolve(os.tmpdir())&&path.basename(scratch).startsWith('h0-goal-'))fs.rmSync(scratch,{recursive:true,force:true});
});
