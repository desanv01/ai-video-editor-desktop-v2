import { spawn, type ChildProcess } from 'node:child_process';
import { createServer, type Socket } from 'node:net';
import { randomBytes, randomUUID, createHmac, timingSafeEqual } from 'node:crypto';
import { net } from 'electron';
import { confined, type Paths } from './util';
import { resolveEngineLaunch } from './engineLaunch';
import { createReceiverTrace, type ReceiverTrace, type ReceiverStage } from './receiverTrace';
import type { CredentialSnapshot } from './credentials';
import type { ComponentManifest } from '../../contracts/rebuild/desktop';
export interface Endpoint { url: string; token: string; signal: AbortSignal }
interface EngineGeneration {
 trace: ReceiverTrace; child: ChildProcess; abort: AbortController; endpoint: Endpoint | null;
 closed: Promise<void>; complete: boolean; stopping: boolean; stopPromise?: Promise<void>;
}
export class Supervisor {
 private child: ChildProcess | null = null; private endpoint: Endpoint | null = null; private abort = new AbortController(); private generation: EngineGeneration | null = null; private starting = false;
 constructor(private paths: Paths, private changed: (state: 'stopped'|'starting'|'ready'|'failed', code?: string) => void) {}
 getEndpoint(): Endpoint { if(!this.endpoint) throw new Error('ENGINE_NOT_READY'); return this.endpoint; }
 cancelStartup(): void { if(this.starting) this.abort.abort(); }
 async start(engine: ComponentManifest, root: string, ffmpegRoot: string, documentsRoot: string, libreofficeBinary: string, whisperRoot: string, whisperBinary: string, whisperModel: string, credentials: CredentialSnapshot = {}): Promise<void> {
  if(this.child||this.starting) throw new Error('ENGINE_ALREADY_RUNNING'); this.starting=true; this.changed('starting'); this.abort=new AbortController();
  const trace=createReceiverTrace(this.paths.logs);trace.mark('start.enter');
  const abort=this.abort; let owned: EngineGeneration | null = null;
  const token=randomBytes(32).toString('hex'), sessionId=randomUUID(), nonce=randomBytes(32).toString('hex');
  const server=createServer(); const sockets=new Set<Socket>();
  let timer: NodeJS.Timeout | undefined; let cancelHandshake: (() => void) | undefined;
  const handshake = new Promise<number>((resolve,reject) => {
   timer=setTimeout(() => {trace.mark('deadline.fire');reject(new Error('ENGINE_START_TIMEOUT'));},30000); trace.mark('timer.armed');
   cancelHandshake=() => {trace.mark('start.cancel');reject(new Error('ENGINE_START_CANCELLED'));};
   abort.signal.addEventListener('abort',cancelHandshake,{once:true});
   server.on('error',error=>{trace.mark('listen.error','fail');reject(error);});
   server.on('connection',socket => { trace.mark('control.connection');sockets.add(socket); socket.setTimeout(5000,() => {trace.mark('socket.timeout');socket.destroy();}); let buffer=Buffer.alloc(0);let observedFirstByte=false;
    socket.on('data',chunk => { buffer=Buffer.concat([buffer,chunk]);if(!observedFirstByte&&chunk.length>0){observedFirstByte=true;trace.mark('control.first-byte');} if(buffer.length>65536) { trace.mark('control.oversize','fail');socket.destroy(); reject(new Error('HANDSHAKE_TOO_LARGE')); return; } const end=buffer.indexOf(10); if(end<0) return;
     trace.mark('control.frame');let receiverStage:ReceiverStage='control.parse';
     try { const h=JSON.parse(buffer.subarray(0,end).toString('utf8'));trace.mark('control.parse','pass');receiverStage='identity.check'; const fields=[h.protocolVersion,h.sessionId,h.nonce,h.pid,h.componentId,h.componentVersion,h.host,h.assignedPort];
      if(h.type!=='aive-engine-startup'||h.protocolVersion!=='desktop.engine-handshake.v2'||h.sessionId!==sessionId||h.nonce!==nonce||h.pid!==this.child?.pid||h.componentId!==engine.id||h.componentVersion!==engine.version||h.host!=='127.0.0.1'||!Number.isInteger(h.assignedPort)||h.assignedPort<1||h.assignedPort>65535||typeof h.hmacSha256!=='string'||!/^[a-f0-9]{64}$/.test(h.hmacSha256)) throw new Error('HANDSHAKE_IDENTITY');
      trace.mark('identity.check','pass');receiverStage='hmac.check';
      const proof=createHmac('sha256',token).update(fields.join('\n')).digest(); if(!timingSafeEqual(proof,Buffer.from(h.hmacSha256,'hex'))) throw new Error('HANDSHAKE_AUTH');trace.mark('hmac.check','pass');trace.mark('handshake.accept'); resolve(h.assignedPort);
     } catch {trace.mark(receiverStage,'fail');trace.mark('handshake.reject','fail'); reject(new Error('HANDSHAKE_REJECTED')); } finally { socket.destroy(); }
    }); socket.on('error',() => {trace.mark('socket.error','fail');}); socket.on('close',() => {trace.mark('socket.close');sockets.delete(socket);});
   });
  });
  // Attach rejection handling before any asynchronous listen/spawn work.
  void handshake.catch(() => {});
  try {
   trace.mark('listen.begin');
   await new Promise<void>((resolve,reject) => { server.once('error',reject); server.listen(0,'127.0.0.1',resolve); });
   const address=server.address(); if(!address || typeof address==='string') throw new Error('CONTROL_BIND_FAILED');trace.mark('listen.bound');
   abort.signal.throwIfAborted();
   const executable=confined(root,engine.entrypoints.engine);
   trace.mark('resolver.begin');const launch=await resolveEngineLaunch(executable,root,abort.signal);trace.mark('resolver.returned'); abort.signal.throwIfAborted();
   const childEnv={...process.env};
   for(const name of Object.keys(childEnv)) if(['MISTRAL_API_KEY','OPENAI_API_KEY','DEEPSEEK_API_KEY','ALIBABA_API_KEY'].includes(name.toUpperCase())) delete childEnv[name];
   trace.mark('spawn.begin');
   this.child=spawn(launch.executable,[],{cwd:launch.cwd,windowsHide:true,shell:false,stdio:'ignore',env:{...childEnv,AIVE_DESKTOP_DATA_ROOT:this.paths.data,AIVE_DESKTOP_COMPONENT_ROOT:this.paths.components,AIVE_FFMPEG_COMPONENT_ROOT:ffmpegRoot,AIVE_DOCUMENTS_COMPONENT_ROOT:documentsRoot,AIVE_LIBREOFFICE_BINARY_PATH:libreofficeBinary,LIBREOFFICE_COMPONENT_ROOT:documentsRoot,LIBREOFFICE_BINARY_PATH:libreofficeBinary,AIVE_WHISPER_COMPONENT_ROOT:whisperRoot,AIVE_WHISPER_BINARY_PATH:whisperBinary,AIVE_WHISPER_MODEL_PATH:whisperModel,WHISPER_CPP_COMPONENT_ROOT:whisperRoot,WHISPER_CPP_BINARY_PATH:whisperBinary,WHISPER_CPP_MODEL_PATH:whisperModel,LOCAL_TRANSCRIPTION_MODEL_PATH:whisperModel,WHISPER_CPP_MODEL_ID:'small',LOCAL_TRANSCRIPTION_MODEL_ID:'small',WHISPER_CPP_MODELS_DIR:'',LOCAL_TRANSCRIPTION_MODELS_DIR:'',AIVE_ENGINE_PORT:'0',AIVE_ENGINE_BEARER_TOKEN:token,AIVE_ENGINE_SESSION_ID:sessionId,AIVE_ENGINE_CONTROL_ADDRESS:`127.0.0.1:${address.port}`,AIVE_ENGINE_CONTROL_NONCE:nonce}});
   const child=this.child;
   // Observe termination immediately after spawn, before handshake or readiness awaits.
   let resolveClosed!: () => void, rejectExited!: (error: Error) => void;
   const closed=new Promise<void>(resolve => { resolveClosed=resolve; });
   const exited=new Promise<never>((_resolve,reject) => { rejectExited=reject; }); void exited.catch(() => {});
   const generation: EngineGeneration={trace,child,abort,endpoint:null,closed,complete:false,stopping:false};
   owned=generation; this.generation=generation;
   const onError=() => {trace.mark('child.error','fail');
    rejectExited(new Error(child.pid?'ENGINE_EXITED':'ENGINE_SPAWN_FAILED'));
    // A failed spawn without a PID never acquired a running process.
    if(!child.pid) { generation.complete=true; resolveClosed(); }
    if(this.generation===generation) { this.endpoint=null; abort.abort(); if(!generation.stopping) this.changed('failed',child.pid?'ENGINE_EXITED':'ENGINE_SPAWN_FAILED'); }
   };
   const onExit=() => {trace.mark('child.exit');
    rejectExited(new Error('ENGINE_EXITED'));
    if(this.generation!==generation) return;
    this.endpoint=null; abort.abort();
    if(!generation.stopping) this.changed('failed','ENGINE_EXITED');
   };
   const onClose=() => {trace.mark('child.close');
    generation.complete=true; resolveClosed();
    child.removeListener('error',onError); child.removeListener('exit',onExit);
    if(this.generation!==generation||generation.stopping) return;
    this.endpoint=null; abort.abort(); this.child=null; this.generation=null;
    this.changed('failed','ENGINE_EXITED');
   };
   child.on('error',onError); child.once('exit',onExit); child.once('close',onClose);trace.mark('spawn.returned');
   const port=await Promise.race([handshake,exited]);
   const endpoint={url:`http://127.0.0.1:${port}`,token,signal:abort.signal};
   generation.endpoint=endpoint;
   trace.mark('readiness.begin');
   const response=await net.fetch(endpoint.url+'/readiness',{headers:{Authorization:`Bearer ${token}`},redirect:'error',signal:AbortSignal.any([abort.signal,AbortSignal.timeout(10000)])});
   trace.mark('readiness.response');trace.mark('readiness.parse','begin');
   const health=await response.json() as { schemaVersion?:string; process?:{alive?:boolean;pid?:number;componentId?:string;componentVersion?:string}; checks?:Record<string,{state?:string}> };
   trace.mark('readiness.parse','pass');
   if(!response.ok||health.schemaVersion!=='desktop.health-readiness.v1'||health.process?.alive!==true||health.process.pid!==child.pid||health.process.componentId!==engine.id||health.process.componentVersion!==engine.version||!['ready','healthy'].includes(health.checks?.api?.state??'')||!['ready','healthy'].includes(health.checks?.database?.state??'')) throw new Error('ENGINE_HEALTH_NOT_READY');trace.mark('readiness.accept','pass');
   if(abort.signal.aborted||this.child!==child) throw new Error('ENGINE_EXITED');
   await this.applyCredentials(endpoint,child,credentials,false,trace);
   if(endpoint.signal.aborted||this.child!==child) throw new Error('CREDENTIAL_SYNC_FAILED');
   this.endpoint=endpoint; this.changed('ready');trace.mark('ready.publish');
  } catch(error) {trace.mark('start.failure','fail'); if(owned && this.generation===owned) await this.stop(); this.changed('failed',error instanceof Error?error.message:'ENGINE_START_FAILED'); throw error; }
  finally { if(timer) clearTimeout(timer); if(cancelHandshake) abort.signal.removeEventListener('abort',cancelHandshake); sockets.forEach(s => s.destroy()); server.close(); this.starting=false;trace.mark('start.final');trace.flush('start-final'); }
 }
 async syncCredentials(snapshot: CredentialSnapshot): Promise<void> {
  const endpoint=this.endpoint, child=this.child;
  if(!endpoint||!child) throw new Error('CREDENTIAL_SYNC_FAILED');
  await this.applyCredentials(endpoint,child,snapshot,true,this.generation?.child===child?this.generation.trace:createReceiverTrace(this.paths.logs));
 }
 private async applyCredentials(endpoint: Endpoint, child: ChildProcess, snapshot: CredentialSnapshot, requireCurrent:boolean, trace:ReceiverTrace): Promise<void> {
  const providers=['mistral','openai','deepseek','alibaba'];
  const owned=() => !endpoint.signal.aborted && this.child===child && (!requireCurrent || this.endpoint===endpoint);
  trace.mark('credential.begin');
  try {
   if(!owned()||!snapshot||typeof snapshot!=='object'||Array.isArray(snapshot)) throw new Error('invalid');
   const names=Object.keys(snapshot).sort();
   if(names.length>4||names.some(name=>!providers.includes(name))) throw new Error('invalid');
   for(const value of Object.values(snapshot)) if(typeof value!=='string'||value.length<1||value.length>8192||/[\x00-\x1f\x7f-\x9f]/.test(value)) throw new Error('invalid');
   const signal=AbortSignal.any([endpoint.signal,AbortSignal.timeout(5000)]);
   const response=await net.fetch(endpoint.url+'/engine-control/credentials',{method:'POST',headers:{Authorization:`Bearer ${endpoint.token}`,'Content-Type':'application/json'},body:JSON.stringify(snapshot),redirect:'error',signal});
   trace.mark('credential.response');
   const ack=await response.json() as {status?:unknown;configuredProviders?:unknown};
   if(signal.aborted||!owned()||!response.ok||ack.status!=='applied'||!Array.isArray(ack.configuredProviders)||ack.configuredProviders.length!==names.length||ack.configuredProviders.some((name,index)=>typeof name!=='string'||name!==names[index])) throw new Error('invalid');
   trace.mark('credential.accept','pass');
  } catch {trace.mark('credential.accept','fail'); throw new Error('CREDENTIAL_SYNC_FAILED'); }
 }
 stop(): Promise<void> {
  const generation=this.generation;const trace=generation?.trace??createReceiverTrace(this.paths.logs);trace.mark('stop.enter');
  // Mark ownership before abort can trigger startup or termination callbacks.
  if(generation) generation.stopping=true;
  this.endpoint=null; this.abort.abort();
  if(!generation) { this.changed('stopped');trace.mark('stop.no-generation');trace.flush('stop-final'); return Promise.resolve(); }
  generation.abort.abort();
  if(generation.stopPromise) return generation.stopPromise;
  const operation=this.stopOwned(generation).then(() => {
   if(this.generation===generation) { this.child=null; this.generation=null; this.changed('stopped'); }trace.mark('stop.confirmed');trace.flush('stop-final');
  },() => {
   // Keep ownership and the close observer so a retry cannot spawn over this child.
   if(this.generation===generation) this.changed('failed','ENGINE_STOP_FAILED');
   trace.mark('stop.failure','fail');trace.flush('stop-final');throw new Error('ENGINE_STOP_FAILED');
  });
  generation.stopPromise=operation;
  void operation.catch(() => { if(generation.stopPromise===operation) generation.stopPromise=undefined; });
  return operation;
 }
 private async waitForClose(generation: EngineGeneration, milliseconds: number): Promise<boolean> {
  if(generation.complete) return true;
  let timer: NodeJS.Timeout | undefined;
  try {
   return await Promise.race([generation.closed.then(() => true),new Promise<false>(resolve => { timer=setTimeout(() => resolve(false),milliseconds); })]);
  } finally { if(timer) clearTimeout(timer); }
 }
 private killOwned(generation: EngineGeneration): void {
  const trace=generation.trace;
  const child=generation.child;
  if(generation.complete||!child.pid||child.exitCode!==null||child.signalCode!==null) return;
  trace.mark('kill.direct-attempt');try { child.kill('SIGKILL');trace.mark('kill.request-returned'); } catch {trace.mark('kill.request-failed','fail'); /* Actual close remains the only success evidence. */ }
 }
 private forceWindows(generation: EngineGeneration): Promise<boolean> {
  const trace=generation.trace;
  return new Promise(resolve => {
   let helper: ChildProcess | undefined, timer: NodeJS.Timeout | undefined, settled=false;
   const finish=(success:boolean) => { if(settled) return; settled=true; if(timer) clearTimeout(timer);trace.mark('force.result',success?'pass':'fail'); resolve(success); };
   try {
    trace.mark('force.begin');helper=spawn('taskkill.exe',['/PID',String(generation.child.pid),'/T','/F'],{windowsHide:true,shell:false,stdio:'ignore'});
    helper.on('error',() => finish(false));
    // Retain this close observer even when timeout settles the bounded helper wait.
    helper.once('close',code => finish(code===0));
    timer=setTimeout(() => {
     trace.mark('force.timeout');
     // This helper is also our own child; never perform global cleanup.
     if(helper?.pid&&helper.exitCode===null&&helper.signalCode===null) { try { helper.kill('SIGKILL'); } catch {} }
     finish(false);
    },5000);trace.mark('force.returned');
   } catch { finish(false); }
  });
 }
 private async stopOwned(generation: EngineGeneration): Promise<void> {
  const trace=generation.trace;
  const endpoint=generation.endpoint;
  if(!generation.complete&&endpoint) { try {trace.mark('shutdown.request'); await net.fetch(endpoint.url+'/engine-control/shutdown',{method:'POST',headers:{Authorization:`Bearer ${endpoint.token}`},redirect:'error',signal:AbortSignal.timeout(2000)});trace.mark('shutdown.returned'); } catch {trace.mark('shutdown.failure','fail');} }
  trace.mark('stop.wait-primary','begin');if(await this.waitForClose(generation,10000)){trace.mark('stop.wait-primary','closed');return;}trace.mark('stop.wait-primary','timeout');
  const child=generation.child;
  // An exit with open stdio still needs close, but its PID must never be killed again.
  if(child.pid&&child.exitCode===null&&child.signalCode===null) {
   if(process.platform==='win32') {
    const killed=await this.forceWindows(generation);
    if(!killed) this.killOwned(generation);
   } else this.killOwned(generation);
  }
  trace.mark('stop.wait-secondary','begin');if(await this.waitForClose(generation,5000)){trace.mark('stop.wait-secondary','closed');return;}trace.mark('stop.wait-secondary','timeout');
  // A successful helper can still leave the owned child alive; attempt its safe fallback.
  this.killOwned(generation);
  trace.mark('stop.wait-final','begin');if(!await this.waitForClose(generation,5000)){trace.mark('stop.wait-final','timeout');throw new Error('ENGINE_STOP_FAILED');}trace.mark('stop.wait-final','closed');
 }
}


