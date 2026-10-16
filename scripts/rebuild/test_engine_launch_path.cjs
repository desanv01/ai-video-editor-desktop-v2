/* Focused source-level regression: real resolver/callsite code, mocked child boundaries.
 * The only native fixture executes cmd's fixed read-only query on a dummy NON-executed file. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const {EventEmitter} = require('node:events');
const {PassThrough} = require('node:stream');
const {spawn} = require('node:child_process');
const root = path.resolve(process.argv[2] || path.join(__dirname, '../..'));
const out = path.resolve(process.argv[3] || path.join(root, '.test-output/engine-launch-path'));
const ts = createRequire(path.join(root, 'desktop/package.json'))('typescript');
const cases = [];
const reused = process.argv[4] ? JSON.parse(fs.readFileSync(path.resolve(process.argv[4]),'utf8')) : null;
function load(name, mocks = {}, processValue = process, extra = '') {
  const file = path.join(root, 'desktop/electron', name+'.ts');
  const code = ts.transpileModule(fs.readFileSync(file,'utf8'), {fileName:file,
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText;
  const module = {exports:{}}; const actual = createRequire(file);
  const timers = [];
  const context = {module,exports:module.exports,require:id=>Object.hasOwn(mocks,id)?mocks[id]:id.startsWith('./')?load(id.slice(2),mocks,processValue).api:actual(id),
    process:processValue,Buffer,URL,AbortController,AbortSignal,console,queueMicrotask,
    setTimeout:(fn,ms)=>{const t=setTimeout(fn,ms);timers.push(t);return t;},clearTimeout};
  vm.runInNewContext(code+extra,context,{filename:file});
  return {api:module.exports,context,timers};
}
function child() {
  const c = new EventEmitter(); Object.assign(c,{pid:1234,exitCode:null,signalCode:null,stdout:new PassThrough(),stderr:new PassThrough(),kills:0});
  c.kill=()=>{c.kills++;return true;};
  c.close=code=>{c.exitCode=code;c.stdout.end();c.stderr.end();c.emit('close',code);};
  return c;
}
const W = path.win32;
const originalExe = String.raw`C:\Owned engine root\bin\aive-engine.exe`;
const shortExe = String.raw`C:\OWNED~1\bin\AIVE-E~1.EXE`;
const originalDir = W.dirname(originalExe), shortDir = W.dirname(shortExe);
function virtual(options={}) {
  const calls=[];let latest;
  function canonical(p) { return W.normalize(p).replace(/^C:\\OWNED~1/i,String.raw`C:\Owned engine root`).replace(/AIVE-E~1\.EXE$/i,'aive-engine.exe'); }
  function id(p){let n=1n;for(const ch of canonical(p).toLowerCase())n=n*31n+BigInt(ch.charCodeAt(0));return n;}
  const file=p=>/\.exe$/i.test(p);
  const fakeFs = {
    lstat:async p=>({isSymbolicLink:()=>!!options.reparse&&W.normalize(p).toLowerCase()===originalDir.toLowerCase()}),
    realpath:async p=>options.realpathConflict&&p===shortExe?String.raw`C:\elsewhere\aive-engine.exe`:canonical(p),
    stat:async (p,o)=>{assert.equal(o.bigint,true);return {ino:options.mismatch&&p===shortExe?999n:id(p),dev:options.zeroId?0n:2n,isFile:()=>file(p),isDirectory:()=>!file(p)};},
  };
  const childProcess = {spawn:(exe,args,opts)=>{
    calls.push({exe,args,opts});latest=child();
    if(options.auto!==false)queueMicrotask(()=>{
      if(options.unavailable){latest.emit('error',Error('unavailable'));latest.close(-1);return;}
      let output=options.output;
      if(output===undefined)output=(options.noAlias?originalExe:shortExe)+'|'+(options.noAlias?originalDir:shortDir)+'\r\n';
      latest.stdout.emit('data',Buffer.from(output,'utf16le'));latest.close(0);
    });
    return latest;
  }};
  const env={SystemRoot:String.raw`C:\Windows`,OPENAI_API_KEY:'SENTINEL_MUST_NOT_REACH_QUERY',ComSpec:String.raw`C:\untrusted\cmd.exe`};
  const loaded=load('engineLaunch',{'node:fs/promises':fakeFs,'node:path':W,'node:child_process':childProcess},{platform:options.platform||'win32',env});
  return {api:loaded.api,calls,get latest(){return latest;},timers:loaded.timers};
}
async function test(name,fn){const accepted=reused?.cases.find(c=>c.name===name&&c.status==='passed');if(accepted){cases.push({...accepted,reusedFrom:path.resolve(process.argv[4])});console.log('reused '+name);return;}try{await fn();cases.push({name,status:'passed'});}catch(e){cases.push({name,status:'failed',error:String(e),stack:e.stack});}console.log(cases.at(-1).status+' '+name);}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function main(){
await fsp.mkdir(out,{recursive:true});
await test('proved-alias-fixed-command-minimal-env-and-same-cwd',async()=>{
  const t=virtual(),r=await t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal);
  assert.equal(r.executable,shortExe);assert.equal(r.cwd,shortDir);assert.equal(t.calls.length,1);
  const q=t.calls[0];assert.equal(q.exe,String.raw`C:\Windows\System32\cmd.exe`);
  assert.deepEqual(Array.from(q.args),['/d','/u','/e:on','/v:off','/s','/c','for %I in (aive-engine.exe) do @for %J in (.) do @echo %~fsI^|%~fsJ']);
  assert.equal(q.opts.cwd,originalDir);assert.equal(q.opts.shell,false);assert.equal(q.opts.windowsVerbatimArguments,undefined);
  assert.deepEqual(Object.keys(q.opts.env).sort(),['SystemRoot','WINDIR']);
  assert.ok(!q.args.join(' ').includes('Owned engine root'));
});
await test('non-Windows-unchanged-without-query',async()=>{const t=virtual({platform:'linux'}),r=await t.api.resolveEngineLaunch('/owned/engine','/owned',new AbortController().signal);assert.equal(r.executable,'/owned/engine');assert.equal(t.calls.length,0);});
await test('nonliteral-Windows-entrypoint-keeps-old-seam-without-filesystem-or-query',async()=>{
  let reads=0,queries=0;
  const denied=new Proxy({}, {get:()=>()=>{reads++;throw Error('ALIAS_ONLY_FILESYSTEM_MUST_NOT_RUN');}});
  const t=load('engineLaunch',{'node:fs/promises':denied,'node:path':W,'node:child_process':{spawn:()=>{queries++;throw Error('MUST_NOT_QUERY');}}},{platform:'win32',env:{SystemRoot:String.raw`C:\Windows`}});
  const exe=String.raw`C:\valid-owned-fixture\engine.exe`,cwd=String.raw`C:\valid-owned-fixture`;
  const r=await t.api.resolveEngineLaunch(exe,cwd,new AbortController().signal);
  assert.equal(r.executable,exe);assert.equal(r.cwd,cwd);assert.equal(reads,0);assert.equal(queries,0);
});
await test('literal-engine-dotted-and-relative-claims-rejected-lexically',async()=>{
  for(const exe of [originalExe.replace(String.raw`\bin`,String.raw`\.\bin`),String.raw`bin\aive-engine.exe`]){
    const t=virtual();await assert.rejects(t.api.resolveEngineLaunch(exe,originalDir,new AbortController().signal),/CANONICAL_PATH/);assert.equal(t.calls.length,0);
  }
});
await test('no-short-name-keeps-canonical-behavior',async()=>{const t=virtual({noAlias:true}),r=await t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal);assert.equal(r.executable,originalExe);assert.equal(r.cwd,originalDir);});
await test('unavailable-query-keeps-canonical-after-child-close',async()=>{const t=virtual({unavailable:true}),r=await t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal);assert.equal(r.executable,originalExe);assert.equal(t.latest.exitCode,-1);});
await test('different-alias-file-denied-without-fallback',async()=>{const t=virtual({mismatch:true});await assert.rejects(t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal),/ALIAS_IDENTITY/);});
await test('alias-realpath-conflict-denied',async()=>{const t=virtual({realpathConflict:true});await assert.rejects(t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal),/ALIAS_REALPATH/);});
await test('canonical-reparse-denied-before-query',async()=>{const t=virtual({reparse:true});await assert.rejects(t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal),/REPARSE/);assert.equal(t.calls.length,0);});
await test('zero-file-identity-denied-before-query',async()=>{const t=virtual({zeroId:true});await assert.rejects(t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal),/FILE_IDENTITY/);assert.equal(t.calls.length,0);});
await test('malformed-extra-output-denied',async()=>{const t=virtual({output:shortExe+'|'+shortDir+'\r\nEXTRA\r\n'});await assert.rejects(t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal),/QUERY_OUTPUT/);});
await test('metacharacter-paths-never-spawn-query',async()=>{for(const ch of ['%','!','^','&','|','<','>','(',')','"','\n']){const t=virtual();const exe=String.raw`C:\owned`+ch+String.raw`root\bin\aive-engine.exe`,dir=W.dirname(exe);const r=await t.api.resolveEngineLaunch(exe,dir,new AbortController().signal);assert.equal(r.executable,exe);assert.equal(t.calls.length,0);}});
await test('already-aborted-does-not-query',async()=>{const t=virtual(),a=new AbortController();a.abort(Error('owned-abort'));await assert.rejects(t.api.resolveEngineLaunch(originalExe,originalDir,a.signal),/owned-abort/);assert.equal(t.calls.length,0);});
await test('cancel-waits-query-close-and-never-falls-back',async()=>{
  const t=virtual({auto:false}),a=new AbortController();let settled=false;
  const pending=t.api.resolveEngineLaunch(originalExe,originalDir,a.signal);pending.then(()=>settled=true,()=>settled=true);
  while(!t.latest)await tick();a.abort(Error('cancel-owned-query'));await tick();
  assert.equal(t.latest.kills,1);assert.equal(settled,false);t.latest.emit('exit',1);await tick();assert.equal(settled,false);
  t.latest.close(1);await assert.rejects(pending,/cancel-owned-query/);
});
await test('timeout-waits-query-close-before-canonical-fallback',async()=>{
  const t=virtual({auto:false});let settled=false;const pending=t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal);pending.then(()=>settled=true,()=>settled=true);
  while(!t.latest)await tick();await new Promise(resolve=>setTimeout(resolve,2050));assert.equal(t.latest.kills,1);assert.equal(settled,false);
  t.latest.close(1);const r=await pending;assert.equal(r.executable,originalExe);
});
await test('output-limit-drains-before-rejection',async()=>{
  const t=virtual({auto:false});let settled=false;const pending=t.api.resolveEngineLaunch(originalExe,originalDir,new AbortController().signal);pending.then(()=>settled=true,()=>settled=true);
  while(!t.latest)await tick();t.latest.stdout.emit('data',Buffer.alloc(8194));await tick();assert.equal(settled,false);assert.equal(t.latest.kills,1);
  t.latest.close(1);await assert.rejects(pending,/OUTPUT_LIMIT/);
});
await test('actual-components-engine-probe-uses-resolver-and-direct-child-cwd',async()=>{
  const resolutions=[],launches=[];const result={schemaVersion:'desktop.engine-self-test.v1',status:'ok',component:'aive-engine',version:'1.0.0',frozen:true};
  const t=load('components',{'./engineLaunch':{resolveEngineLaunch:async(exe,cwd,signal)=>{resolutions.push({exe,cwd,signal});return{executable:'selected-engine',cwd:'selected-probe-cwd'};}},
    'node:fs/promises':{lstat:async()=>({isFile:()=>true,isSymbolicLink:()=>false})},
    'node:child_process':{spawn:(exe,args,opts)=>{launches.push({exe,args,opts});const c=child();queueMicrotask(()=>{c.stdout.emit('data',Buffer.from(JSON.stringify(result)));c.close(0);});return c;}}},process,'\nmodule.exports.testProbe=probe;');
  const signal=new AbortController().signal;await t.api.testProbe({id:'aive-engine',version:'1.0.0',entrypoints:{engine:'bin/aive-engine.exe'},probes:[{kind:'engine-self-test',entrypoint:'engine'}]},String.raw`C:\owned`,signal);
  assert.equal(resolutions.length,1);assert.equal(resolutions[0].cwd,path.dirname(resolutions[0].exe));assert.equal(resolutions[0].signal,signal);
  assert.equal(launches.length,1);assert.equal(launches[0].exe,'selected-engine');assert.equal(launches[0].opts.cwd,'selected-probe-cwd');assert.equal(launches[0].opts.shell,false);
});
await test('other-component-probe-does-not-use-engine-resolver',async()=>{
  let calls=0;const t=load('components',{'./engineLaunch':{resolveEngineLaunch:async()=>{calls++;throw Error('wrong component');}},
    'node:fs/promises':{lstat:async()=>({isFile:()=>true,isSymbolicLink:()=>false})},
    'node:child_process':{spawn:()=>{const c=child();queueMicrotask(()=>{c.stdout.emit('data',Buffer.from('ffmpeg version fixture'));c.close(0);});return c;}}},process,'\nmodule.exports.testProbe=probe;');
  await t.api.testProbe({id:'ffmpeg',version:'1',entrypoints:{ffmpeg:'bin/ffmpeg.exe'},probes:[{kind:'ffmpeg-version',entrypoint:'ffmpeg'}]},String.raw`C:\owned`,new AbortController().signal);assert.equal(calls,0);
});
await test('actual-Supervisor-uses-shared-resolver-and-direct-engine-spawn',async()=>{
  const resolutions=[],launches=[];const server=new EventEmitter();server.listen=(_p,_h,fn)=>fn();server.address=()=>({port:12345});server.close=()=>{};
  const t=load('supervisor',{'electron':{net:{}},'./engineLaunch':{resolveEngineLaunch:async(exe,cwd,signal)=>{resolutions.push({exe,cwd,signal});return{executable:'selected-engine',cwd:'selected-runtime-cwd'};}},
    'node:net':{createServer:()=>server},'node:child_process':{spawn:(exe,args,opts)=>{launches.push({exe,args,opts});throw Error('CAPTURE_ONLY_NO_ENGINE');}}});
  const paths={root:String.raw`C:\owned`,data:String.raw`C:\owned\Data`,components:String.raw`C:\owned\Components`};
  const instance=new t.api.Supervisor(paths,()=>{});
  await assert.rejects(instance.start({entrypoints:{engine:'bin/aive-engine.exe'}},String.raw`C:\owned\component`,'','','','','',''),/CAPTURE_ONLY_NO_ENGINE/);
  assert.equal(resolutions.length,1);assert.equal(resolutions[0].cwd,String.raw`C:\owned\component`);assert.equal(launches.length,1);
  assert.equal(launches[0].exe,'selected-engine');assert.equal(launches[0].opts.cwd,'selected-runtime-cwd');assert.equal(launches[0].opts.shell,false);
});
await test('actual-read-only-query-Unicode-spaces-dummy-file-never-executed',async()=>{
  if(process.platform!=='win32'){cases.push({name:'native-fixture-qualification',status:'qualified-non-Windows'});return;}
  const fixture=await fsp.mkdtemp(path.join(out,'query-fixture-'));const component=path.join(fixture,'Unicode \u5b66\u751f ordinary spaces'),bin=path.join(component,'bin');await fsp.mkdir(bin,{recursive:true});
  const exe=path.join(bin,'aive-engine.exe');await fsp.writeFile(exe,'NONEXECUTABLE_DUMMY_QUERY_ONLY',{flag:'wx'});
  const queries=[];const t=load('engineLaunch',{'node:child_process':{spawn:(command,args,opts)=>{assert.equal(command,path.join(process.env.SystemRoot,'System32','cmd.exe'));assert.ok(!args.join(' ').includes(fixture));assert.deepEqual(Object.keys(opts.env).sort(),['SystemRoot','WINDIR']);queries.push({command,args,cwd:opts.cwd});return spawn(command,args,opts);}}});
  for(const cwd of [bin,component]){const r=await t.api.resolveEngineLaunch(exe,cwd,new AbortController().signal);assert.equal((await fsp.realpath(r.executable)).toLowerCase(),exe.toLowerCase());assert.equal((await fsp.realpath(r.cwd)).toLowerCase(),cwd.toLowerCase());}
  assert.equal(queries.length,2);assert.ok(queries[0].args.at(-1).includes('for %J in (.)'));assert.ok(queries[1].args.at(-1).includes('for %J in (..)'));
  await fsp.writeFile(path.join(fixture,'query-facts.json'),JSON.stringify({queries,dummyFileNeverExecuted:true,qualifiedAliasAvailability:true},null,2));
});
const receipt={status:cases.every(c=>c.status!=='failed')?'passed':'failed',scope:'Focused actual resolver/callsite source transpilation, mocked engine children; native query of dummy file only. No realengine/app/build.',cases};
await fsp.writeFile(path.join(out,'focused-tests.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));process.exitCode=receipt.status==='passed'?0:1;
}
main().catch(async error=>{console.error(error);await fsp.mkdir(out,{recursive:true});await fsp.writeFile(path.join(out,'focused-harness-failed.json'),JSON.stringify({error:String(error),stack:error.stack,cases},null,2));process.exitCode=1;});
