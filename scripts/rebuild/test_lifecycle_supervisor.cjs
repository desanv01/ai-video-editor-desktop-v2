'use strict';
// Main-owned owned-process lifecycle boundaries with explicit child/net substitutes.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test'),net=require('node:net');
const {EventEmitter}=require('node:events'),{createRequire}=require('node:module'),{createHmac}=require('node:crypto');
const root=path.resolve(process.argv[2]||path.join(__dirname,'../..')),compiled=path.join(root,'desktop/dist-electron/desktop/electron');
function load(name,mocks={}){const file=path.join(compiled,name+'.js'),module={exports:{}},actual=createRequire(file);vm.runInNewContext(fs.readFileSync(file,'utf8'),{module,exports:module.exports,require:id=>Object.hasOwn(mocks,id)?mocks[id]:actual(id),__dirname:path.dirname(file),__filename:file,process,Buffer,URL,Headers,Request,Response,AbortController,AbortSignal,setTimeout:(fn,ms)=>setTimeout(fn,ms===10000?50:ms===5000?30:ms),clearTimeout,queueMicrotask,console},{filename:file});return module.exports;}
const util=load('util'),engine={id:'aive-engine',version:util.RELEASE,entrypoints:{engine:'engine.exe'}};
function child(pid){const c=new EventEmitter();Object.assign(c,{pid,exitCode:null,signalCode:null,kills:[]});c.kill=s=>{c.kills.push(s);return true;};return c;}
async function fixture(t,{helperMode='success',closeFallback=true,badCredentials=false,holdHandshake=false}={}){
 const engineChild=child(43210),calls=[],states=[];let helper,spawnedResolve;const spawned=new Promise(r=>spawnedResolve=r);let bad=badCredentials;
 const spawn=(exe,args,options)=>{
  calls.push({exe,args,options});assert.equal(options.windowsHide,true);assert.equal(options.shell,false);
  if(exe==='taskkill.exe'){
   assert.deepEqual(Array.from(args),['/PID','43210','/T','/F']);
   if(helperMode==='throw')throw Error('spawn-helper-detail');helper=child(98765);helper.kill=s=>{helper.kills.push(s);queueMicrotask(()=>helper.emit('close',1));return true;};
   if(helperMode==='error')queueMicrotask(()=>helper.emit('error',Error('helper-error')));
   if(helperMode==='nonzero')queueMicrotask(()=>helper.emit('close',1));
   if(helperMode==='success')queueMicrotask(()=>helper.emit('close',0));
   return helper;
  }
  assert.equal(args.length,0);for(const name of ['MISTRAL_API_KEY','OPENAI_API_KEY','DEEPSEEK_API_KEY','ALIBABA_API_KEY'])assert.equal(options.env[name],undefined);
  engineChild.kill=s=>{engineChild.kills.push(s);if(closeFallback)queueMicrotask(()=>{engineChild.signalCode=s;engineChild.emit('exit',null,s);engineChild.emit('close',null,s);});return true;};
  spawnedResolve();if(!holdHandshake)queueMicrotask(()=>{const e=options.env,h={type:'aive-engine-startup',protocolVersion:'desktop.engine-handshake.v2',sessionId:e.AIVE_ENGINE_SESSION_ID,nonce:e.AIVE_ENGINE_CONTROL_NONCE,pid:engineChild.pid,componentId:'aive-engine',componentVersion:util.RELEASE,host:'127.0.0.1',assignedPort:32123};h.hmacSha256=createHmac('sha256',e.AIVE_ENGINE_BEARER_TOKEN).update([h.protocolVersion,h.sessionId,h.nonce,h.pid,h.componentId,h.componentVersion,h.host,h.assignedPort].join('\n')).digest('hex');const [host,port]=e.AIVE_ENGINE_CONTROL_ADDRESS.split(':');const sock=net.connect(+port,host,()=>sock.end(JSON.stringify(h)+'\n'));sock.on('error',()=>{});});return engineChild;
 };
 const fetch=async(url,opt)=>{
  if(url.endsWith('/readiness'))return new Response(JSON.stringify({schemaVersion:'desktop.health-readiness.v1',process:{alive:true,pid:engineChild.pid,componentId:'aive-engine',componentVersion:util.RELEASE},checks:{api:{state:'ready'},database:{state:'ready'}}}));
  if(url.endsWith('/credentials'))return new Response(JSON.stringify({status:bad?'wrong':'applied',configuredProviders:[]}));
  if(url.endsWith('/shutdown'))return new Response('{}');throw Error('Unexpected endpoint');
 };
 const {Supervisor}=load('supervisor',{'node:child_process':{spawn},electron:{net:{fetch}}});const s=new Supervisor({data:root,components:root},(state,code)=>states.push({state,code}));
 t.after(async()=>{if(s.child){engineChild.exitCode=0;engineChild.emit('exit',0);engineChild.emit('close',0);await s.stop().catch(()=>{});}});
 const start=()=>s.start(engine,root,root,root,'',root,'','');const startPromise=start();
 if(holdHandshake){await spawned;return {s,engineChild,calls,states,startPromise};}
 if(badCredentials)await assert.rejects(startPromise,/CREDENTIAL_SYNC_FAILED/);else await startPromise;
 return {s,engineChild,calls,states,start,setBad:v=>bad=v,getHelper:()=>helper};
}
test('stop shares promise and hides endpoint immediately; exit alone never resolves or clears owned child',async t=>{const f=await fixture(t),endpoint=f.s.getEndpoint();const a=f.s.stop(),b=f.s.stop();assert.equal(a,b);assert.equal(endpoint.signal.aborted,true);assert.throws(()=>f.s.getEndpoint(),/ENGINE_NOT_READY/);let done=false;a.then(()=>done=true);f.engineChild.exitCode=0;f.engineChild.emit('exit',0);await new Promise(r=>setImmediate(r));assert.equal(done,false);assert.equal(f.s.child,f.engineChild);assert.equal(f.states.at(-1).state,'ready');f.engineChild.emit('close',0);await a;assert.equal(f.s.child,null);assert.equal(f.states.at(-1).state,'stopped');});
test('successful taskkill helper never proves engine shutdown; owned fallback waits for child close',async t=>{const f=await fixture(t);await f.s.stop();assert.ok(f.calls.some(c=>c.exe==='taskkill.exe'));assert.deepEqual(f.engineChild.kills,['SIGKILL']);assert.equal(f.states.at(-1).state,'stopped');assert.equal(f.s.child,null);});
test('taskkill spawn failure/error/nonzero/hang use only owned fallback and confirm close',async t=>{for(const helperMode of ['throw','error','nonzero','hang']){const f=await fixture(t,{helperMode});await f.s.stop();assert.deepEqual(f.engineChild.kills,['SIGKILL']);assert.equal(f.s.child,null);assert.equal(f.states.at(-1).state,'stopped');if(helperMode==='hang')assert.deepEqual(f.getHelper().kills,['SIGKILL']);}});
test('unconfirmed shutdown fails honestly, retains ownership and blocks restart; later close permits stop retry',async t=>{const f=await fixture(t,{closeFallback:false});await assert.rejects(f.s.stop(),e=>e.message==='ENGINE_STOP_FAILED');assert.equal(f.s.child,f.engineChild);assert.equal(f.states.at(-1).code,'ENGINE_STOP_FAILED');await assert.rejects(f.start(),/ENGINE_ALREADY_RUNNING/);assert.ok(!f.states.some(v=>v.state==='stopped'));f.engineChild.exitCode=0;f.engineChild.emit('exit',0);f.engineChild.emit('close',0);assert.equal(f.s.child,f.engineChild);await f.s.stop();assert.equal(f.s.child,null);assert.equal(f.states.at(-1).state,'stopped');});
test('exited PID with pending close is never force killed or treated as complete',async t=>{const f=await fixture(t);f.engineChild.exitCode=0;f.engineChild.emit('exit',0);const stopping=f.s.stop();setTimeout(()=>f.engineChild.emit('close',0),65);await stopping;assert.ok(!f.calls.some(c=>c.exe==='taskkill.exe'));assert.equal(f.engineChild.kills.length,0);assert.equal(f.states.at(-1).state,'stopped');});
test('credential startup failure terminates owned generation before retry, with no ready state',async t=>{const f=await fixture(t,{badCredentials:true});assert.equal(f.s.child,null);assert.ok(!f.states.some(v=>v.state==='ready'));assert.equal(f.states.at(-1).state,'failed');});
test('cancelling an in-flight startup rejects promptly and confirms owned close before returning',async t=>{const f=await fixture(t,{holdHandshake:true});f.s.cancelStartup();await assert.rejects(f.startPromise,/ENGINE_START_CANCELLED/);assert.equal(f.s.child,null);assert.equal(f.states.at(-1).state,'failed');});
