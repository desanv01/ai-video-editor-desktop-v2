'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=process.argv[2],out=process.argv[3];
const {_electron}=require(process.env.AIVE_TEST_PLAYWRIGHT_MODULE || require.resolve('playwright',{paths:[path.join(root,'desktop')]}));
(async()=>{
 await fs.mkdir(out,{recursive:true});
 const isolated=path.join(out,'isolated-profile');await fs.mkdir(isolated,{recursive:true});
 const env={...process.env,LOCALAPPDATA:isolated};delete env.ELECTRON_RUN_AS_NODE;delete env.AIVE_DEV_URL;delete env.AIVE_DEVELOPER_MODE;
 const app=await _electron.launch({executablePath:path.join(root,'desktop/release-electron/win-unpacked/AIVE Desktop.exe'),env,timeout:30000});
 try{
  const page=await app.firstWindow();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.getByRole('heading',{name:'Prepare your editing workspace'}).waitFor({timeout:20000});
  await page.getByRole('alert').filter({hasText:'PACKS_UNCONFIGURED'}).waitFor();
  const snapshot=await page.locator('body').innerText();await fs.writeFile(path.join(out,'setup-snapshot.txt'),snapshot);
  const state=await page.evaluate(()=>window.aiveDesktop.getState());
  assert.equal(state.setupComplete,false);assert.equal(state.error.code,'PACKS_UNCONFIGURED');assert.equal(state.engineState,'stopped');
  const boundary=await page.evaluate(()=>({require:typeof require,process:typeof process,bridge:Object.keys(window.aiveDesktop),url:location.href}));
  assert.equal(boundary.require,'undefined');assert.equal(boundary.process,'undefined');assert.equal(boundary.bridge.includes('getCredential'),false);assert.equal(boundary.url,'aive://app/');
  const rejected=await page.evaluate(async()=>{try{await window.aiveDesktop.setCredential('unknown-provider','test');return false;}catch{return true;}});assert.equal(rejected,true);
  await page.getByRole('button',{name:'Retry preparation'}).click();await page.getByRole('alert').filter({hasText:'PACKS_UNCONFIGURED'}).waitFor();
  await page.screenshot({path:path.join(out,'setup-1280.png')});
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2));
  await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
  const capture=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  await fs.writeFile(path.join(out,'setup-200-percent.png'),Buffer.from(capture,'base64'));
  const scroll=await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,mainWidth:document.querySelector('main').clientWidth,mainScrollWidth:document.querySelector('main').scrollWidth}));assert.ok(scroll.documentWidth<=scroll.width);assert.ok(scroll.mainScrollWidth<=scroll.mainWidth);
  assert.deepEqual(errors,[]);
  const preferences=await app.evaluate(({BrowserWindow})=>{const p=BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();return {sandbox:p.sandbox,contextIsolation:p.contextIsolation,nodeIntegration:p.nodeIntegration,webSecurity:p.webSecurity};});
  assert.deepEqual(preferences,{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true});
  await fs.writeFile(path.join(out,'electron-smoke.json'),JSON.stringify({status:'passed',scope:'Real unpacked Electron window and preload, no backend/runtime packs or installed installer acceptance',state,boundary,preferences,errors,scroll},null,2));
  console.log('Electron window, honest unavailable setup, IPC validation, isolated renderer and 200% overflow checks passed.');
 }finally{await app.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
