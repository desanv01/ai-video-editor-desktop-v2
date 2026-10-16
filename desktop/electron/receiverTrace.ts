import fs from 'node:fs/promises';
import path from 'node:path';

// Bounded local receiver diagnostics; asynchronous checkpoints do not establish startup acceptance.
export const RECEIVER_DIAGNOSTICS_ENABLED = true;
export const STAGES = ['start.enter','timer.armed','deadline.fire','start.cancel','listen.begin','listen.bound','listen.error',
 'resolver.begin','resolver.returned','spawn.begin','spawn.returned','control.connection','control.first-byte','control.frame',
 'control.oversize','control.parse','identity.check','hmac.check','handshake.accept','handshake.reject','socket.timeout','socket.error','socket.close',
 'child.error','child.exit','child.close','readiness.begin','readiness.response','readiness.parse','readiness.accept',
 'credential.begin','credential.response','credential.accept','ready.publish','start.failure','start.final',
 'stop.enter','stop.no-generation','stop.confirmed','stop.failure','shutdown.request','shutdown.returned','shutdown.failure',
 'stop.wait-primary','stop.wait-secondary','stop.wait-final','force.begin','force.returned','force.result','force.timeout',
 'kill.direct-attempt','kill.request-returned','kill.request-failed'] as const;
export type ReceiverStage = typeof STAGES[number];
export const OUTCOMES = ['observed','begin','returned','pass','fail','closed','timeout'] as const;
export type ReceiverOutcome = typeof OUTCOMES[number];
type Boundary = 'start-final'|'stop-final';
type Event = {sequence:number; elapsedNs:string; stage:ReceiverStage; outcome:ReceiverOutcome; previousStage:ReceiverStage|null};
export interface ReceiverTrace {
 readonly traceId:string;
 mark(stage:ReceiverStage,outcome?:ReceiverOutcome):void;
 flush(boundary:Boundary):void;
 status():Record<string,unknown>;
 drainForReview():Promise<void>;
}
type Options = {enabled?:boolean; clock?:()=>bigint; utc?:()=>string; sink?:(packet:string,attempt:number)=>Promise<void>};
const stages = new Set<string>(STAGES), outcomes = new Set<string>(OUTCOMES);
const LIMIT=256, FLUSH_LIMIT=4, BYTE_LIMIT=65536;
const registry:ReceiverTrace[]=[]; let registryOverflow=false; let ordinal=0;let initializationFailures=0;
const increment=(value:number)=>Math.min(Number.MAX_SAFE_INTEGER,value+1);
function inert(traceId:string,fault=false):ReceiverTrace {
 if(fault)initializationFailures=increment(initializationFailures);
 return Object.freeze({traceId,mark:()=>{},flush:()=>{},status:()=>({traceId,enabled:false,recorderInitializationFailed:fault,evidenceAvailable:false,senderStages:'UNOBSERVED'}),drainForReview:()=>Promise.resolve()});
}
async function privateWrite(directory:string,name:string,text:string):Promise<void> {
 if(!path.isAbsolute(directory)||Buffer.byteLength(text,'utf8')>BYTE_LIMIT)throw new Error('PRIVATE_CHECKPOINT_INVALID');
 for(let current=directory;;current=path.dirname(current)) {
  if((await fs.lstat(current)).isSymbolicLink())throw new Error('PRIVATE_CHECKPOINT_REPARSE');
  if(path.dirname(current)===current)break;
 }
 if(path.resolve(await fs.realpath(directory)).toLowerCase()!==path.resolve(directory).toLowerCase())throw new Error('PRIVATE_CHECKPOINT_REALPATH');
 const handle=await fs.open(path.join(directory,name),'wx',0o600);
 try{await handle.writeFile(text,'utf8');await handle.sync();}finally{await handle.close();}
}
export function createReceiverTrace(directory:string,options:Options={}):ReceiverTrace {
 ordinal=increment(ordinal);const traceId='receiver-'+ordinal.toString();
 try {
  if(!(options.enabled??RECEIVER_DIAGNOSTICS_ENABLED))return inert(traceId);
  const clock=options.clock??(()=>process.hrtime.bigint());const origin=clock();
  if(typeof origin!=='bigint'||origin<0n||origin>2n**128n-1n)return inert(traceId,true);
  const anchor=(options.utc??(()=>new Date().toISOString()))();
  if(typeof anchor!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(anchor))return inert(traceId,true);
  const events:Event[]=[];let previous:ReceiverStage|null=null,last=origin;
  let sequence=0,revision=0,overflow=0,rejected=0,clockFailures=0,flushAttempts=0,flushSucceeded=0,flushFailed=0,flushSuppressed=0,pending=0,nativeIoPending=0,flushTimeouts=0,checkpointBlocked=false,terminal=false;
  type Coverage={revision:number;lastSequence:number;terminalObserved:boolean;boundary:Boundary|null};
  let boundary:Boundary|null=null,requested:Coverage|null=null,persisted:Coverage|null=null;
  let queue=Promise.resolve();
  const dirty=()=>{revision=increment(revision);};
  const coverage=():Coverage=>({revision,lastSequence:sequence,terminalObserved:terminal,boundary});
  const observations=()=>({traceId,utcAnchor:anchor,bufferLimit:LIMIT,retained:events.length,totalObserved:sequence,
   overflowCount:overflow,rejectedInputCount:rejected,clockFailureCount:clockFailures,
   observationIncomplete:overflow>0||rejected>0||clockFailures>0,coverage:coverage()});
  const status=()=>({enabled:true,...observations(),flushAttempts,flushSucceeded,flushFailed,flushSuppressed,flushTimeouts,
   pendingFlushes:pending,nativeIoPending,checkpointBlocked,checkpointDecisionBudgetMs:500,
   currentCoverage:coverage(),lastRequestedCoverage:requested?{...requested}:null,successfullyPersistedCoverage:persisted?{...persisted}:null,
   currentObservationPersisted:persisted!==null&&persisted.revision===revision&&persisted.lastSequence===sequence&&persisted.boundary===boundary,
   terminalObserved:terminal,evidenceAvailable:false,senderStages:'UNOBSERVED',acceptance:'NONE_REQUIRES_MAIN_POSTFLUSH_STATUS_AND_OWNERSHIP'});
  const trace:ReceiverTrace={
   traceId,
   mark(stage,outcome='observed') {
    try {
     if(typeof stage!=='string'||!stages.has(stage)||typeof outcome!=='string'||!outcomes.has(outcome)){rejected=increment(rejected);dirty();return;}
     const instant=clock();if(typeof instant!=='bigint'||instant<last||instant>2n**128n-1n){clockFailures=increment(clockFailures);dirty();return;}
     last=instant;sequence=increment(sequence);dirty();
     const event:Event={sequence,elapsedNs:(instant-origin).toString(),stage,outcome,previousStage:previous};previous=stage;
     if(events.length===LIMIT){events.shift();overflow=increment(overflow);}events.push(event);
     if(stage==='ready.publish'||stage==='start.failure'||stage==='stop.confirmed'||stage==='stop.failure')terminal=true;
    }catch{clockFailures=increment(clockFailures);dirty();}
   },
   flush(nextBoundary) {
    try {
     if(nextBoundary!=='start-final'&&nextBoundary!=='stop-final'){rejected=increment(rejected);dirty();return;}
     if(flushAttempts>=FLUSH_LIMIT){flushSuppressed=increment(flushSuppressed);dirty();return;}
     boundary=nextBoundary;dirty();
     const attempt=++flushAttempts;pending++;
     // Serialize NOW: queued I/O never combines old events with mutable later status.
     const captured=coverage();requested={...captured};
     const packet=JSON.stringify({schema:'aive.private-supervisor-receiver.v2',traceId,boundary:nextBoundary,
      monotonicClock:'process-local hrtime.bigint nanoseconds, decimal strings',events:events.map(event=>({...event})),
      capturedObservation:observations(),senderStages:'UNOBSERVED',acceptance:'NONE_REQUIRES_MAIN_POSTFLUSH_STATUS_AND_OWNERSHIP'});
     queue=queue.then(async()=>{
      let decisionTimer:NodeJS.Timeout|undefined;
      try {
       if(checkpointBlocked){flushSuppressed=increment(flushSuppressed);dirty();return;}
       if(Buffer.byteLength(packet,'utf8')>BYTE_LIMIT)throw new Error('CHECKPOINT_SIZE');
       nativeIoPending++;
       const io=Promise.resolve().then(()=>options.sink?options.sink(packet,attempt):privateWrite(directory,'supervisor-receiver-'+origin.toString()+'-'+traceId+'-'+attempt+'.json',packet));
       const tracked=io.then(()=>{nativeIoPending--;},()=>{nativeIoPending--;throw new Error('CHECKPOINT_IO_FAILURE');});
       await Promise.race([tracked,new Promise<never>((_,reject)=>{decisionTimer=setTimeout(()=>{flushTimeouts=increment(flushTimeouts);checkpointBlocked=true;dirty();reject(new Error('CHECKPOINT_TIMEOUT'));},500);})]);
       flushSucceeded=increment(flushSucceeded);
       // Only the successfully completed captured revision advances this watermark.
       if(!persisted||captured.revision>persisted.revision)persisted={...captured};
      }catch{
       flushFailed=increment(flushFailed);dirty();
       try{console.warn('SUPERVISOR_DIAGNOSTIC_CHECKPOINT_FAILED');}catch{/* No raw exceptions; product outcome is untouched. */}
      }finally{if(decisionTimer)clearTimeout(decisionTimer);pending--;}
     }).catch(()=>{flushFailed=increment(flushFailed);dirty();pending=Math.max(0,pending-1);});
    }catch{flushFailed=increment(flushFailed);dirty();}
   },
   status(){try{return{...status()};}catch{return{traceId,enabled:true,recorderStatusFailed:true,evidenceAvailable:false};}},
   drainForReview(){return queue.then(()=>{},()=>{});}
  };
  Object.defineProperty(trace,'traceId',{value:traceId,enumerable:true,writable:false,configurable:false});
  if(registry.length===4){registry.shift();registryOverflow=true;}registry.push(trace);
  return trace;
 }catch{return inert(traceId,true);}
}
// Read-only safe status/explicit review drain; no renderer IPC and no product caller awaits this I/O.
export function receiverDiagnosticsStatus():Record<string,unknown> {
 try{return{schema:'aive.private-receiver-status.v1',configuredEnabled:RECEIVER_DIAGNOSTICS_ENABLED,registryOverflow,initializationFailures,observationIncomplete:registryOverflow||initializationFailures>0,
  traces:registry.map(trace=>trace.status()),senderStages:'UNOBSERVED',acceptance:'NONE_IF_LOG_OR_POSTFLUSH_STATUS_ABSENT'};}
 catch{return{statusFailed:true,evidenceAvailable:false};}
}
export function drainReceiverDiagnosticsForReview():Promise<void> {
 try{return Promise.all(registry.map(trace=>trace.drainForReview())).then(()=>{},()=>{});}catch{return Promise.resolve();}
}
