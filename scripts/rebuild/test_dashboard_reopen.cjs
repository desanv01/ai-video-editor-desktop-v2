'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),Module=require('node:module');
const [repoArg,outArg,modulesArg,electronArg]=process.argv.slice(2),repo=path.resolve(repoArg),out=path.resolve(outArg),modules=path.resolve(modulesArg||path.join(repo,'desktop/node_modules'));
fs.mkdirSync(out,{recursive:false});const desktop=Module.createRequire(path.join(modules,'../package.json')),esbuild=desktop('esbuild'),{_electron}=desktop('playwright');
const component=path.join(repo,'desktop/src/components/ProjectDashboard.tsx').replaceAll('\\','/');
const apiStub=[
"export const listProjects=async()=>window.fixture.projects;",
"export const listVideos=async()=>window.fixture.videos;",
"export const getProductReadiness=async()=>null;",
"export const getProcessingStatus=async()=>({progress_percent:30});",
"export const friendlyErrorMessage=error=>String(error.message||error);",
"export async function getVideo(id){ window.calls.push({method:'getVideo',id});const f=window.fixture;if(f.error)throw Error(f.error);if(f.delay)return new Promise(resolve=>{window.resolveDetail=()=>resolve(f.details[id]);});return f.details[id];}",
"export const createProject=async()=>{window.calls.push({method:'FORBIDDEN-create'});throw Error('No creation');};",
"export const retryVideoProcessing=async()=>{window.calls.push({method:'FORBIDDEN-processing'});throw Error('No analysis');};",
"export const deleteProject=async()=>{throw Error('No deletion');};",
"export const updateProject=async()=>{throw Error('No mutation');};"
].join('\n');
const entry="import React from 'react';import{createRoot}from'react-dom/client';import{ProjectDashboard}from"+JSON.stringify(component)+";let root;window.mountFixture=f=>{if(root)root.unmount();window.fixture=f;window.calls=[];window.targets=[];delete window.resolveDetail;root=createRoot(document.getElementById('root'));root.render(React.createElement(ProjectDashboard,{onContinue:target=>window.targets.push(target)}));};window.unmountFixture=()=>root.unmount();";
const cases=[];let app;
async function main(){
 await esbuild.build({stdin:{contents:entry,resolveDir:repo,sourcefile:'dashboard-reopen-test.tsx',loader:'tsx'},bundle:true,platform:'browser',format:'iife',jsx:'automatic',nodePaths:[modules],outfile:path.join(out,'component.js'),plugins:[{name:'private-read-fixture',setup(build){build.onResolve({filter:/(^|\/)lib\/api$/},()=>({path:'api-fixture',namespace:'fixture'}));build.onLoad({filter:/.*/,namespace:'fixture'},()=>({contents:apiStub,loader:'js'}));}}]});
 fs.writeFileSync(path.join(out,'index.html'),'<!doctype html><html><body><div id="root"></div><script src="./component.js"></script></body></html>');
 fs.writeFileSync(path.join(out,'main.cjs'),"const{app,BrowserWindow}=require('electron');app.whenReady().then(()=>{const w=new BrowserWindow({width:1500,height:1000,show:false,webPreferences:{nodeIntegration:false,contextIsolation:true}});w.loadFile(require('path').join(__dirname,'index.html'));});app.on('window-all-closed',()=>app.quit());");
 const env={...process.env};for(const key of Object.keys(env))if(key.startsWith('AIVE_')||key.endsWith('_API_KEY')||key==='ELECTRON_RUN_AS_NODE')delete env[key];
 const executable=electronArg||path.join(modules,'electron/dist/electron.exe');assert.ok(fs.existsSync(executable),'Pinned Electron runtime absent: '+executable);console.log('Interaction runtime: '+executable);env.DEBUG='pw:browser';\n app=await _electron.launch({executablePath:executable,args:[path.join(out,'main.cjs'),'--user-data-dir='+path.join(out,'shell')],env,timeout:60000});const page=await app.firstWindow();await page.waitForFunction(()=>typeof window.mountFixture==='function');
 const project=(id,title)=>({id,title,description:'Owned interaction fixture',status:'failed',source_mode:'single_video',project_type:'lecture',metadata_json:{},created_at:'2026-10-08T00:00:00',updated_at:'2026-10-08T00:00:00'});
 const video=(id,pid,status)=>({id,project_id:pid,project_asset_id:null,original_filename:id+'.mp4',duration_seconds:36.5,resolution:'1280x720',status,error_message:null,created_at:'2026-10-08T00:00:00',updated_at:'2026-10-08T00:00:00'});
 const a=video('video-a','project-a','failed'),b=video('video-b','project-b','completed');
 const fixture=(detail,extra={})=>({projects:[project('project-a','Candidate A'),project('project-b','Candidate B')],videos:[a,b],details:{'video-a':detail},...extra});
 async function mount(f){await page.evaluate(f=>window.mountFixture(f),f);await page.getByRole('button',{name:'Open project Candidate A',exact:true}).waitFor();}
 async function clickA(){await page.getByRole('button',{name:'Open project Candidate A',exact:true}).click();}
 async function target(view,id='project-a'){await page.waitForFunction(()=>window.targets.length>0);const targets=await page.evaluate(()=>window.targets);assert.equal(targets.length,1);assert.equal(targets[0].nextView,view);assert.equal(targets[0].project.id,id);assert.ok((await page.evaluate(()=>window.calls)).every(c=>!c.method.startsWith('FORBIDDEN')));}
 async function test(name,fn){try{await fn();cases.push({name,status:'passed'});}catch(e){cases.push({name,status:'failed',error:String(e)});}console.log(cases.at(-1).status+' '+name);}
 await test('failed-render-with-real-saved-plan-opens-review',async()=>{await mount(fixture({...a,edit_plan:{id:'saved-approved-plan',is_approved:true,teacher_notes:'Retained edit'}}));await clickA();await target('review');assert.deepEqual(await page.evaluate(()=>window.calls),[{method:'getVideo',id:a.id}]);});
 await test('failed-before-plan-stays-intake',async()=>{await mount(fixture({...a,edit_plan:null}));await clickA();await target('upload');});
 await test('refreshed-busy-status-opens-processing',async()=>{await mount(fixture({...a,status:'analyzing',edit_plan:null}));await clickA();await target('processing');});
 await test('refreshed-completed-status-opens-review',async()=>{await mount(fixture({...a,status:'completed',edit_plan:{id:'saved'}}));await clickA();await target('review');});
 await test('normal-completed-project-no-detail-request',async()=>{await mount(fixture({...a,edit_plan:null}));await page.getByRole('button',{name:'Open project Candidate B',exact:true}).click();await target('review','project-b');assert.deepEqual(await page.evaluate(()=>window.calls),[]);});
 await test('read-error-visible-without-routing-or-processing',async()=>{await mount(fixture(null,{error:'Owned detail read failure'}));await clickA();await page.getByText('Owned detail read failure',{exact:true}).waitFor();assert.deepEqual(await page.evaluate(()=>window.targets),[]);});
 await test('older-response-cannot-replace-new-project-selection',async()=>{await mount(fixture({...a,edit_plan:{id:'saved'}},{delay:true}));await clickA();await page.waitForFunction(()=>typeof window.resolveDetail==='function',{timeout:2500});await page.getByRole('button',{name:'Open project Candidate B',exact:true}).click();await target('review','project-b');await page.evaluate(()=>window.resolveDetail());await page.waitForTimeout(100);await target('review','project-b');});
 await test('unmounted-dashboard-cannot-navigate-after-late-response',async()=>{await mount(fixture({...a,edit_plan:{id:'saved'}},{delay:true}));await clickA();await page.waitForFunction(()=>typeof window.resolveDetail==='function',{timeout:2500});await page.evaluate(()=>{window.unmountFixture();window.resolveDetail();});await page.waitForTimeout(100);assert.deepEqual(await page.evaluate(()=>window.targets),[]);});
}
main().catch(e=>{cases.push({name:'interaction-harness',status:'failed',error:String(e)});console.error(String(e));}).finally(async()=>{if(app)await app.close();const receipt={status:cases.length===8&&cases.every(c=>c.status==='passed')?'passed':'failed',scope:'Actual production ProjectDashboard mounted with real React in owned Electron and clicked through Playwright. Only API reads are controlled fixtures; no provider/backend/profile changes or auto analysis.',cases};fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));process.exitCode=receipt.status==='passed'?0:1;});