/* Receiver diagnostic regressions use in-memory sockets, children and fetch.
 * Optional second argument compares an explicitly supplied previous emitted Supervisor. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {EventEmitter}=require('node:events'),{createRequire}=require('node:module'),crypto=require('node:crypto');
const root=path.resolve(process.argv[2]||path.join(__dirname,'../..'));
const candidate=path.join(root,'desktop/dist-electron/desktop/electron');
const baseline=process.argv[3]?path.resolve(process.argv[3]):null;
function load(file,mocks={},extras={}){
 const module={exports:{}},actual=createRequire(file);
 vm.runInNewContext(fs.readFileSync(file,'utf8'),{module,exports:module.exports,require:id=>Object.hasOwn(mocks,id)?mocks[id]:actual(id),
  process,Buffer,URL,AbortController,AbortSignal,console,setTimeout,clearTimeout,...extras},{filename:file});return module.exports;
}
function recorder(){return load(path.join(candidate,'receiverTrace.js'));}
async function redactionAndBounds(){
 const r=recorder(),packets=[];let clock=10n;
 const trace=r.createReceiverTrace('unused-private-path',{enabled:true,clock:()=>++clock,utc:()=> '2026-10-16T00:00:00.000Z',sink:async text=>{packets.push(JSON.parse(text));}});
 const secret='DO_NOT_EMIT_TOKEN_NONCE_BODY_ENV';
 trace.mark(secret,'observed');trace.mark('control.frame',{toString(){throw Error(secret);}});
 trace.mark('control.frame','observed',{token:secret,sessionId:secret,nonce:secret,hmac:secret,environment:secret});
 for(let i=0;i<300;i++)trace.mark('control.connection');trace.mark('start.failure','fail');trace.flush('start-final');await trace.drainForReview();
 const status=trace.status();assert.equal(status.retained,256);assert.ok(status.overflowCount>0);assert.equal(status.rejectedInputCount,2);assert.equal(status.evidenceAvailable,false);
 const encoded=JSON.stringify(packets);assert.ok(!encoded.includes(secret));assert.ok(!encoded.includes('"pid"'));assert.ok(!encoded.includes('"environment"'));
 for(const packet of packets){assert.ok(Buffer.byteLength(JSON.stringify(packet))<=65536);assert.equal(packet.senderStages,'UNOBSERVED');for(const event of packet.events){assert.match(event.elapsedNs,/^[0-9]+$/);assert.ok(r.STAGES.includes(event.stage));}}
}
async function recorderFailureAndMissingEvidence(){
 const r=recorder(),message='SECRET_FROM_FAILED_WRITER';
 const trace=r.createReceiverTrace('unused',{enabled:true,sink:async()=>{throw Error(message);}});
 assert.equal(trace.status().evidenceAvailable,false);trace.mark('start.failure','fail');assert.doesNotThrow(()=>trace.flush('start-final'));await trace.drainForReview();
 assert.equal(trace.status().flushFailed,1);assert.equal(trace.status().evidenceAvailable,false);assert.ok(!JSON.stringify(r.receiverDiagnosticsStatus()).includes(message));
 let calls=0;const disabled=r.createReceiverTrace('unused',{enabled:false,sink:async()=>{calls++;}});disabled.mark('start.enter');disabled.flush('start-final');await disabled.drainForReview();assert.equal(calls,0);
 let count=0;const badClock=r.createReceiverTrace('unused',{enabled:true,clock:()=>{if(++count>1)throw Error(message);return 1n;},sink:async()=>{}});
 assert.doesNotThrow(()=>badClock.mark('timer.armed'));assert.equal(badClock.status().clockFailureCount,1);
}
async function boundedCheckpointDecision(){
 const r=recorder(),trace=r.createReceiverTrace('unused',{enabled:true,sink:()=>new Promise(()=>{})});
 trace.mark('start.failure','fail');for(let i=0;i<8;i++)trace.flush('start-final');
 await trace.drainForReview();const status=trace.status();assert.equal(status.flushAttempts,4);assert.ok(status.flushSuppressed>=4);assert.equal(status.flushTimeouts,1);assert.equal(status.nativeIoPending,1);assert.equal(status.successfullyPersistedCoverage,null);assert.equal(status.currentObservationPersisted,false);assert.equal(status.evidenceAvailable,false);
}
async function supervisorScenario(directory,mode,writerFails,restart=false){
 const r=recorder(),packets=[],wireSecrets=[],handlers=[],states=[],timers=[];let clock=100n;
 const traces=[];const makeTrace=()=>{const value=r.createReceiverTrace('unused',{enabled:true,clock:()=>++clock,sink:async text=>{if(writerFails)throw Error('SECRET_WRITER_ERROR');packets.push(JSON.parse(text));}});traces.push(value);return value;};
 let trace;let lastSocket;
 let server;const makeServer=()=>{server=new EventEmitter();server.listen=(_p,_h,fn)=>queueMicrotask(fn);server.address=()=>({port:43210});server.close=()=>{};return server;};
 let engine;
 function closeChild(child,code){child.exitCode=code;child.emit('exit',code);child.emit('close',code);}
 function child(){const c=new EventEmitter();c.pid=77;c.exitCode=null;c.signalCode=null;c.kill=()=>{closeChild(c,1);return true;};const on=c.on.bind(c),once=c.once.bind(c);c.on=(name,fn)=>{handlers.push('on:'+name);return on(name,fn);};c.once=(name,fn)=>{handlers.push('once:'+name);return once(name,fn);};return c;}
 const fakeTimers=(fn,ms)=>{const token={fn,ms};timers.push(token);if(ms===10000)queueMicrotask(fn);return token;};
 const spawn=(exe,args,options)=>{
  if(exe==='taskkill.exe'){const helper=child();helper.pid=88;queueMicrotask(()=>{closeChild(engine,1);closeChild(helper,0);});return helper;}
  engine=child();queueMicrotask(()=>{
   if(mode==='deadline'){timers.find(t=>t.ms===30000).fn();return;}
   const env=options.env;wireSecrets.push(env.AIVE_ENGINE_BEARER_TOKEN,env.AIVE_ENGINE_SESSION_ID,env.AIVE_ENGINE_CONTROL_NONCE);
   const h={type:'aive-engine-startup',protocolVersion:'desktop.engine-handshake.v2',sessionId:env.AIVE_ENGINE_SESSION_ID,nonce:env.AIVE_ENGINE_CONTROL_NONCE,pid:mode==='identity-fail'?78:77,componentId:'aive-engine',componentVersion:'2.1.0-rebuild.2',host:'127.0.0.1',assignedPort:43211};
   h.hmacSha256=crypto.createHmac('sha256',env.AIVE_ENGINE_BEARER_TOKEN).update([h.protocolVersion,h.sessionId,h.nonce,h.pid,h.componentId,h.componentVersion,h.host,h.assignedPort].join('\n')).digest('hex');wireSecrets.push(h.hmacSha256);
   if(mode==='hmac-fail')h.hmacSha256='0'.repeat(64);
   const socket=new EventEmitter();lastSocket=socket;socket.setTimeout=(ms,fn)=>{assert.equal(ms,5000);return socket;};socket.destroy=()=>{if(mode==='identity-fail')queueMicrotask(()=>closeChild(engine,1));};
   server.emit('connection',socket);const bytes=mode==='oversize'?Buffer.alloc(65537,120):Buffer.from(mode==='malformed'?'{bad json\n':JSON.stringify(h)+'\n'),cut=Math.floor(bytes.length/2);socket.emit('data',bytes.subarray(0,cut));socket.emit('data',bytes.subarray(cut));
  });return engine;
 };
 const fetch=async url=>({ok:true,json:async()=>url.endsWith('/readiness')?{schemaVersion:'desktop.health-readiness.v1',process:{alive:true,pid:77,componentId:'aive-engine',componentVersion:'2.1.0-rebuild.2'},checks:{api:{state:'ready'},database:{state:'ready'}}}:{status:'applied',configuredProviders:['openai']}});
 const api=load(path.join(directory,'supervisor.js'),{'electron':{net:{fetch}},'node:net':{createServer:makeServer},'node:child_process':{spawn},
  './util':{confined:(root,name)=>path.join(root,name)},'./engineLaunch':{resolveEngineLaunch:async(exe,cwd)=>({executable:exe,cwd})},'./receiverTrace':{createReceiverTrace:()=>{trace=makeTrace();return trace;}}},
  {setTimeout:fakeTimers,clearTimeout:()=>{},process:{platform:'win32',env:{}}});
 const subject=new api.Supervisor({logs:'private',data:'data',components:'components'},(...args)=>states.push(args));let error;
 const start=()=>subject.start({id:'aive-engine',version:'2.1.0-rebuild.2',entrypoints:{engine:'bin/aive-engine.exe'}},'owned-root','','','','','','',{openai:'SECRET_CREDENTIAL_VALUE'});
 try{await start();}catch(e){error=e.message;}
 let restartAttribution;
 if(restart){
  assert.equal(error,undefined);const oldTrace=trace,oldSocket=lastSocket;closeChild(engine,0);
  await start();const newTrace=trace;assert.notEqual(oldTrace.traceId,newTrace.traceId);
  const oldBefore=oldTrace.status().totalObserved,newBefore=newTrace.status().totalObserved;
  oldSocket.emit('error',Error('OLD_CALLBACK_SECRET'));
  restartAttribution={oldBefore,newBefore,oldAfter:oldTrace.status().totalObserved,newAfter:newTrace.status().totalObserved,
   oldTraceId:oldTrace.traceId,newTraceId:newTrace.traceId};
 }
 await Promise.all(traces.map(value=>value.drainForReview()));
 const encoded=JSON.stringify(packets);for(const value of [...wireSecrets,'SECRET_CREDENTIAL_VALUE','SECRET_WRITER_ERROR','openai'])assert.ok(!encoded.includes(value));
 return{error,states,handlers,packets,status:trace?.status()??{},restartAttribution,
  ownedDisposition:{childPresent:subject.child!==null,generationPresent:subject.generation!==null,endpointPresent:subject.endpoint!==null,engineClosed:engine.exitCode!==null||engine.signalCode!==null},
  deadlineDurations:timers.filter(t=>t.ms===30000).map(t=>t.ms)};
}
async function actualOrderingAndFailureSafety(){
 const normal=await supervisorScenario(candidate,'valid',false);assert.equal(normal.error,undefined);assert.deepEqual(normal.deadlineDurations,[30000]);
 const events=normal.packets.flatMap(p=>p.events),first=name=>events.findIndex(e=>e.stage===name);
 const order=['timer.armed','listen.begin','listen.bound','resolver.begin','resolver.returned','spawn.begin','spawn.returned','control.connection','control.first-byte','control.frame','control.parse','identity.check','hmac.check','handshake.accept','readiness.begin','readiness.response','readiness.accept','credential.begin','credential.accept','ready.publish'];
 for(let i=1;i<order.length;i++)assert.ok(first(order[i])>first(order[i-1]),order[i]);
 for(const mode of ['valid','identity-fail','hmac-fail','malformed','oversize','deadline']){
  const instrumented=await supervisorScenario(candidate,mode,true);
  if(baseline){
   const original=await supervisorScenario(baseline,mode,false);
   assert.equal(instrumented.error,original.error);assert.deepEqual(instrumented.states,original.states);assert.deepEqual(instrumented.handlers,original.handlers);assert.deepEqual(instrumented.deadlineDurations,original.deadlineDurations);
   assert.deepEqual(instrumented.ownedDisposition,original.ownedDisposition);
  }else{
   // Fixed original contract: no candidate-to-itself substitute for a previous build.
   const expectedError={valid:undefined,'identity-fail':'HANDSHAKE_REJECTED','hmac-fail':'HANDSHAKE_REJECTED',malformed:'HANDSHAKE_REJECTED',oversize:'HANDSHAKE_TOO_LARGE',deadline:'ENGINE_START_TIMEOUT'}[mode];
   const ready=mode==='valid';
   assert.equal(instrumented.error,expectedError);
   assert.deepEqual(instrumented.deadlineDurations,[30000]);
   assert.deepEqual(instrumented.states[0],['starting']);
   assert.deepEqual(instrumented.states.at(-1),ready?['ready']:['failed',expectedError]);
   assert.equal(instrumented.states.some(state=>state[0]==='ready'),ready);
   assert.deepEqual(instrumented.ownedDisposition,{childPresent:ready,generationPresent:ready,endpointPresent:ready,engineClosed:!ready});
   assert.deepEqual(instrumented.handlers.slice(0,5),['on:error','once:exit','on:exit','once:close','on:close']);
  }
  assert.ok(instrumented.status.flushFailed>0);assert.equal(instrumented.status.evidenceAvailable,false);
 }
 for(const [mode,phase] of [['malformed','control.parse'],['identity-fail','identity.check'],['hmac-fail','hmac.check']]){
  const result=await supervisorScenario(candidate,mode,false);const events=result.packets.flatMap(p=>p.events);
  assert.equal(result.error,'HANDSHAKE_REJECTED');assert.ok(events.some(e=>e.stage==='control.frame'));
  assert.ok(events.some(e=>e.stage===phase&&e.outcome==='fail'));
  if(mode==='hmac-fail')assert.ok(events.some(e=>e.stage==='identity.check'&&e.outcome==='pass'));
 }
 const oversize=await supervisorScenario(candidate,'oversize',false);assert.equal(oversize.error,'HANDSHAKE_TOO_LARGE');
 assert.ok(oversize.packets.flatMap(p=>p.events).some(e=>e.stage==='control.oversize'&&e.outcome==='fail'));
 assert.ok(!oversize.packets.flatMap(p=>p.events).some(e=>e.stage==='control.frame'));
 const twice=await supervisorScenario(candidate,'valid',false,true);const attribution=twice.restartAttribution;
 assert.equal(attribution.oldAfter,attribution.oldBefore+1);assert.equal(attribution.newAfter,attribution.newBefore);
 const newPacket=twice.packets.find(p=>p.traceId===attribution.newTraceId);assert.equal(newPacket.events[0].sequence,1);
 assert.equal(newPacket.events[0].stage,'start.enter');
 const deadline=await supervisorScenario(candidate,'deadline',false);const stages=deadline.packets.flatMap(p=>p.events).map(e=>e.stage);
 for(const name of ['deadline.fire','stop.enter','stop.wait-primary','force.begin','force.result','stop.confirmed'])assert.ok(stages.includes(name),name);
}
async function immutableCoverageRegressions(){
 const r=recorder(),packets=[];let release;
 const trace=r.createReceiverTrace('unused',{enabled:true,sink:async text=>{packets.push(JSON.parse(text));}});
 trace.mark('start.enter');trace.flush('start-final');await trace.drainForReview();
 assert.equal(trace.status().currentObservationPersisted,true);
 trace.mark('start.failure','fail');assert.equal(trace.status().currentObservationPersisted,false);
 assert.equal(trace.status().successfullyPersistedCoverage.terminalObserved,false);
 trace.flush('start-final');await trace.drainForReview();assert.equal(trace.status().currentObservationPersisted,true);
 trace.mark('socket.close');assert.equal(trace.status().currentObservationPersisted,false);
 assert.equal(trace.status().evidenceAvailable,false);
 const queued=[];const second=r.createReceiverTrace('unused',{enabled:true,sink:async(text,attempt)=>{
  queued.push(JSON.parse(text));if(attempt===1)await new Promise(resolve=>{release=resolve;});
 }});
 second.mark('start.enter');second.flush('start-final');
 // Allow first queued writer to enter its injected Promise (no wall clock sleep).
 for(let i=0;i<20&&!release;i++)await Promise.resolve();assert.equal(typeof release,'function');
 const firstRevision=second.status().lastRequestedCoverage.revision;
 second.mark('ready.publish');second.flush('start-final');
 const secondRevision=second.status().lastRequestedCoverage.revision;
 second.mark('socket.close');release();await second.drainForReview();
 assert.equal(queued[0].capturedObservation.coverage.revision,firstRevision);
 assert.equal(queued[0].capturedObservation.coverage.terminalObserved,false);
 assert.equal(queued[0].events.at(-1).stage,'start.enter');
 assert.equal(queued[1].capturedObservation.coverage.revision,secondRevision);
 assert.equal(queued[1].capturedObservation.coverage.terminalObserved,true);
 assert.equal(queued[1].events.at(-1).stage,'ready.publish');
 assert.equal(second.status().successfullyPersistedCoverage.revision,secondRevision);
 assert.equal(second.status().currentObservationPersisted,false);
 assert.ok(second.status().currentCoverage.revision>secondRevision);
 assert.equal(second.status().evidenceAvailable,false);
 const failed=r.createReceiverTrace('unused',{enabled:true,sink:async()=>{throw Error('IO');}});
 failed.mark('ready.publish');failed.flush('start-final');await failed.drainForReview();
 assert.equal(failed.status().successfullyPersistedCoverage,null);
 assert.equal(failed.status().currentObservationPersisted,false);
}
(async()=>{await redactionAndBounds();await recorderFailureAndMissingEvidence();await boundedCheckpointDecision();await actualOrderingAndFailureSafety();await immutableCoverageRegressions();console.log('RECEIVER_DIAGNOSTIC_CASES_PASS_NO_NATIVE_APP_ENGINE');})().catch(error=>{console.error(error);process.exitCode=1;});
