import fs from 'node:fs/promises';
import { createReadStream, createWriteStream } from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { pipeline } from 'node:stream/promises';
import { Transform } from 'node:stream';
import https from 'node:https';
import yauzl from 'yauzl';
import type { ComponentManifest, ReleaseManifest, DesktopState, SetupPhase } from '../../contracts/rebuild/desktop';
import { atomic, confined, relative, readJson, RELEASE, type Paths } from './util';
const kinds=new Set(['engine-self-test','ffmpeg-version','ffprobe-version','filter-codec-check','whisper-runtime','whisper-model','document-tool-version']);
export function validateManifest(value: unknown): ReleaseManifest {
 const m=value as ReleaseManifest; if(!m||m.schemaVersion!=='aive.components.v1'||m.releaseVersion!==RELEASE||m.platform!=='win32'||m.architecture!=='x64'||!Array.isArray(m.components)||m.components.length>30) throw new Error('MANIFEST_INCOMPATIBLE');
 const ids=new Set<string>();
 for(const c of m.components) {
  if(!c||!/^[a-z][a-z0-9-]{1,63}$/.test(c.id)||ids.has(c.id)||typeof c.version!=='string'||!/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/.test(c.version)||!relative(c.archive)||!c.archive.endsWith('.zip')||!/^[a-f0-9]{64}$/.test(c.sha256)||!Number.isSafeInteger(c.sizeBytes)||c.sizeBytes<=0||!Number.isSafeInteger(c.expandedBytes)||c.expandedBytes<=0||typeof c.required!=='boolean'||!c.entrypoints||!Object.keys(c.entrypoints).length||!Object.values(c.entrypoints).every(relative)||!Array.isArray(c.probes)||!c.probes.length) throw new Error('MANIFEST_COMPONENT_INVALID');
  ids.add(c.id);
  if(c.url) { const u=new URL(c.url); if(u.protocol!=='https:'||u.username||u.password||u.hash) throw new Error('MANIFEST_URL_INVALID'); }
  for(const p of c.probes) if(!kinds.has(p.kind)||!Object.hasOwn(c.entrypoints,p.entrypoint)||p.args && (!Array.isArray(p.args)||p.args.some(a => typeof a!=='string'||a.length>512||a.includes('\0')))) throw new Error('MANIFEST_PROBE_INVALID');
  for(const p of c.probes) if(p.kind==='whisper-model' && (!p.runtimeEntrypoint || !p.audioEntrypoint || !Object.hasOwn(c.entrypoints,p.runtimeEntrypoint) || !Object.hasOwn(c.entrypoints,p.audioEntrypoint) || typeof p.expectedText!=='string' || p.expectedText.length<5 || p.expectedText.length>200)) throw new Error('WHISPER_JOINT_PROBE_NOT_CONFIGURED');
 }
 return m;
}
interface WhisperBindings { whisperRoot:string;whisperBinary:string;whisperModel:string }
interface Active { schemaVersion: 'aive.activation.v1'; releaseVersion: string; current: Record<string,{version:string;sha256:string}>; previous: Record<string,{version:string;sha256:string}> }
interface Journal { operationId:string; selected:string[]; totalBytes:number; phase:SetupPhase; acquiredBytes:number; completedWork:number }
async function hash(file: string, signal: AbortSignal): Promise<string> { const result=createHash('sha256'); for await(const chunk of createReadStream(file,{signal})) result.update(chunk); return result.digest('hex'); }
async function sizeOf(root:string):Promise<number> { let size=0; for(const entry of await fs.readdir(root,{withFileTypes:true}).catch(() => [])) { const file=path.join(root,entry.name); if(entry.isDirectory()) size+=await sizeOf(file); else if(entry.isFile()) size+=(await fs.stat(file)).size; } return size; }
export class Components {
 private manifest: ReleaseManifest = {schemaVersion:'aive.components.v1',releaseVersion:RELEASE,platform:'win32',architecture:'x64',components:[]};
 private active:Active={schemaVersion:'aive.activation.v1',releaseVersion:RELEASE,current:{},previous:{}};
 private abort:AbortController|null=null; private busy=false;
 private legacyRoots=new Map<string,string>();
 constructor(private paths:Paths,private manifestFile:string,private offline:string[],private publish:(patch:Partial<DesktopState>)=>void) {}
 async initialize():Promise<void> {
  this.legacyRoots.clear();
  this.manifest=validateManifest(JSON.parse(await fs.readFile(this.manifestFile,'utf8')));
  this.active=await readJson(path.join(this.paths.state,'active.json'),this.active);
  const validBindings=(value:unknown):boolean => !!value&&typeof value==='object'&&!Array.isArray(value)&&Object.entries(value).every(([id,binding]) => /^[a-z][a-z0-9-]{1,63}$/.test(id)&&!!binding&&typeof binding==='object'&&!Array.isArray(binding)&&typeof binding.version==='string'&&/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/.test(binding.version)&&typeof binding.sha256==='string'&&/^[a-f0-9]{64}$/.test(binding.sha256));
  if(!this.active||this.active.schemaVersion!=='aive.activation.v1'||!validBindings(this.active.current)||!validBindings(this.active.previous)) throw new Error('ACTIVATION_STATE_INVALID');
  for(const c of this.manifest.components) {
   const current=Object.hasOwn(this.active.current,c.id)?this.active.current[c.id]:undefined;
   if(!current||current.version!==c.version||current.sha256!==c.sha256) continue;
   const legacy=confined(this.paths.components,c.id+'/'+c.version);
   if(!await this.normalRoot(legacy)) continue;
   const marker=await readJson<{sha256?:string;version?:string}|null>(path.join(legacy,'.verified.json'),null);
   if(marker?.sha256===c.sha256&&marker.version===c.version) this.legacyRoots.set(this.identity(c),legacy);
  }
  const journal=await readJson<Journal|null>(path.join(this.paths.state,'preparation.json'),null);
  const states=await Promise.all(this.manifest.components.map(async c => ({id:c.id,version:c.version,phase:'checking' as SetupPhase,bytes:0,installed:await this.installed(c)})));
  this.publish({components:states,phase:'awaiting_confirmation',canRetry:true,error:journal && !['ready','cancelled'].includes(journal.phase)?{code:'PREPARATION_INTERRUPTED',message:'Preparation was interrupted. Retry will reuse verified downloads.',retryable:true}:null});
  if(!this.configured()) this.publish({phase:'error',error:{code:'PACKS_UNCONFIGURED',message:'This engineering shell has no configured engine, media or document packs. A release with verified runtime packs is required.',retryable:true},canRetry:true});
 }
 configured():boolean { return ['aive-engine','ffmpeg','documents'].every(id => this.manifest.components.some(c => c.id===id&&c.required)); }
 private async installed(c:ComponentManifest):Promise<boolean> {
  const current=Object.hasOwn(this.active.current,c.id)?this.active.current[c.id]:undefined; if(!current||current.version!==c.version||current.sha256!==c.sha256) return false;
  const root=this.root(c); if(!await this.normalRoot(root)) return false; const marker=await readJson<{sha256?:string;version?:string}|null>(path.join(root,'.verified.json'),null); if(marker?.sha256!==c.sha256||marker.version!==c.version) return false;
  for(const entry of Object.values(c.entrypoints)) { try { const stat=await fs.lstat(confined(root,entry)); if(!stat.isFile()||stat.isSymbolicLink()) return false; } catch { return false; } } return true;
 }
 private identity(c:ComponentManifest):string { return c.id+'/'+c.version+'/'+c.sha256; }
 private canonicalRoot(c:ComponentManifest):string { return confined(this.paths.components,c.id+'/'+c.sha256.slice(0,16)); }
 private async normalRoot(root:string):Promise<boolean> {
  try {
   const info=await fs.lstat(root); if(!info.isDirectory()||info.isSymbolicLink()) return false;
   // Reject a directory reached through a junction or linked ancestor as well.
   const actual=path.resolve(await fs.realpath(root)), expected=path.resolve(root);
   return process.platform==='win32'?actual.toLowerCase()===expected.toLowerCase():actual===expected;
  } catch(error) { if((error as NodeJS.ErrnoException).code==='ENOENT') return false; throw error; }
 }
 private async assertActivationRoot(root:string):Promise<void> {
  const boundary=path.resolve(this.paths.components);
  // Validate existing target and ancestors before mkdir can follow a link.
  for(let current=root;;current=path.dirname(current)) {
   try {
    const info=await fs.lstat(current);
    if(!info.isDirectory()||info.isSymbolicLink()) throw new Error('IMMUTABLE_VERSION_CONFLICT');
    const actual=path.resolve(await fs.realpath(current)), expected=path.resolve(current);
    if(process.platform==='win32'?actual.toLowerCase()!==expected.toLowerCase():actual!==expected) throw new Error('IMMUTABLE_VERSION_CONFLICT');
   } catch(error) { if((error as NodeJS.ErrnoException).code!=='ENOENT'||current===boundary) throw error; }
   if(current===boundary) break;
  }
 }
 root(c:ComponentManifest):string { return this.legacyRoots.get(this.identity(c))??this.canonicalRoot(c); }
 async engine():Promise<{engine:ComponentManifest;root:string;ffmpegRoot:string;documentsRoot:string;libreofficeBinary:string;whisperRoot:string;whisperBinary:string;whisperModel:string}> {
  const engine=this.manifest.components.find(c => c.id==='aive-engine'); const ffmpeg=this.manifest.components.find(c => c.id==='ffmpeg'); const documents=this.manifest.components.find(c => c.id==='documents');
  if(!engine||!ffmpeg||!documents||!await this.installed(engine)||!await this.installed(ffmpeg)||!await this.installed(documents)) throw new Error('REQUIRED_COMPONENTS_MISSING');
  if(documents.entrypoints.libreoffice!=='program/soffice.com') throw new Error('DOCUMENT_ENTRYPOINT_INVALID');
  const documentsRoot=this.root(documents); const libreofficeBinary=confined(documentsRoot,documents.entrypoints.libreoffice);
  return {engine,root:this.root(engine),ffmpegRoot:this.root(ffmpeg),documentsRoot,libreofficeBinary,...await this.whisperBindings()};
 }
 private async whisperBindings():Promise<WhisperBindings> {
  const empty={whisperRoot:'',whisperBinary:'',whisperModel:''};
  const candidates=this.manifest.components.filter(c => c.probes.some(p => p.kind==='whisper-model'));
  if(candidates.length!==1) return empty;
  const c=candidates[0];
  if(c.id!=='whisper-small'||c.entrypoints.whisper!=='bin/whisper-cli.exe'||c.entrypoints.model!=='models/ggml-small.bin'||c.entrypoints.audio!=='probes/jfk.wav') return empty;
  if(!c.probes.some(p => p.kind==='whisper-runtime'&&p.entrypoint==='whisper')||!c.probes.some(p => p.kind==='whisper-model'&&p.entrypoint==='model'&&p.runtimeEntrypoint==='whisper'&&p.audioEntrypoint==='audio'&&typeof p.expectedText==='string'&&p.expectedText.trim().length>=5)||!await this.installed(c)) return empty;
  const whisperRoot=this.root(c);const whisperBinary=confined(whisperRoot,c.entrypoints.whisper);const whisperModel=confined(whisperRoot,c.entrypoints.model);
  try {
   for(const target of [whisperRoot,whisperBinary,whisperModel,confined(whisperRoot,c.entrypoints.audio)]) {
    for(let current=target;;current=path.dirname(current)) {
     const info=await fs.lstat(current);if(info.isSymbolicLink())return empty;
     if(path.dirname(current)===current)break;
    }
    const actual=path.resolve(await fs.realpath(target));const expected=path.resolve(target);
    if(process.platform==='win32'?actual.toLowerCase()!==expected.toLowerCase():actual!==expected)return empty;
   }
  } catch {return empty;}
  return {whisperRoot,whisperBinary,whisperModel};
 }
 async localTranscriptionReady(bound?:WhisperBindings):Promise<boolean> {
  const active=await this.whisperBindings();
  return !!active.whisperRoot&&(!bound||(active.whisperRoot===bound.whisperRoot&&active.whisperBinary===bound.whisperBinary&&active.whisperModel===bound.whisperModel));
 }
 async markReady():Promise<void> { const file=path.join(this.paths.state,'preparation.json'); const journal=await readJson<Journal|null>(file,null); if(journal) await atomic(file,{...journal,phase:'ready'}); }
 async allRequiredInstalled():Promise<boolean> { if(!this.configured()) return false; for(const c of this.manifest.components.filter(c => c.required)) if(!await this.installed(c)) return false; return true; }
 cancel():void { this.abort?.abort(); }
 async prepare():Promise<void> {
  if(this.busy) throw new Error('PREPARATION_BUSY'); if(!this.configured()) throw new Error('PACKS_UNCONFIGURED'); this.busy=true; this.abort=new AbortController(); const signal=this.abort.signal;
  const selected=this.manifest.components.filter(c => c.required); const journal:Journal={operationId:randomUUID(),selected:selected.map(c => c.id),totalBytes:selected.reduce((n,c)=>n+c.sizeBytes,0),phase:'checking',acquiredBytes:0,completedWork:0}; const totalWork=selected.length*4;
  const states=selected.map(c => ({id:c.id,version:c.version,phase:'checking' as SetupPhase,bytes:0,installed:false}));
  const update=async(phase:SetupPhase,c?:ComponentManifest,bytes?:number) => { journal.phase=phase; if(c) { const state=states.find(s => s.id===c.id)!; state.phase=phase; if(bytes!==undefined) state.bytes=bytes; } journal.acquiredBytes=states.reduce((n,s)=>n+s.bytes,0); this.publish({phase,components:states.map(s=>({...s})),error:null,canCancel:!['activating','ready'].includes(phase),canRetry:false,progress:{...journal,totalWork}}); await atomic(path.join(this.paths.state,'preparation.json'),journal); };
  const staging=confined(this.paths.components,'staging-'+journal.operationId); const staged=new Map<string,string>();
  try {
   await fs.mkdir(staging,{recursive:true});
   for(const c of selected) {
    signal.throwIfAborted(); if(await this.installed(c)) { states.find(s=>s.id===c.id)!.installed=true; states.find(s=>s.id===c.id)!.bytes=c.sizeBytes; journal.completedWork+=4; await update('checking',c); continue; }
    const disk=await fs.statfs(this.paths.components); const retained=await sizeOf(path.join(this.paths.components,c.id)); const need=c.sizeBytes+c.expandedBytes+retained+256*1024*1024; if(disk.bavail*disk.bsize<need) throw new Error('DISK_SPACE_LOW');
    await update('acquiring',c); let lastProgress=0; const archive=await this.acquire(c,signal,bytes=>{ states.find(s=>s.id===c.id)!.bytes=bytes;const now=Date.now();if(now-lastProgress<100&&bytes<c.sizeBytes)return;lastProgress=now; this.publish({components:states.map(s=>({...s})),progress:{operationId:journal.operationId,selected:journal.selected,totalBytes:journal.totalBytes,acquiredBytes:states.reduce((n,s)=>n+s.bytes,0),completedWork:journal.completedWork,totalWork}}); });
    journal.completedWork++; await update('verifying',c,c.sizeBytes); if(await hash(archive,signal)!==c.sha256) { await fs.rm(archive,{force:true}); await fs.rm(archive+'.json',{force:true}); throw new Error('COMPONENT_HASH_MISMATCH'); } journal.completedWork++;
    await update('extracting',c); const target=confined(staging,c.id); await fs.mkdir(target,{recursive:true}); await extract(archive,target,c.expandedBytes,signal); journal.completedWork++;
    await update('probing',c); await probe(c,target,signal); await atomic(path.join(target,'.verified.json'),{sha256:c.sha256,version:c.version}); staged.set(c.id,target);
   }
   signal.throwIfAborted(); await update('activating');
   const identitiesUnchanged=selected.every(c => {
    const current=Object.hasOwn(this.active.current,c.id)?this.active.current[c.id]:undefined;
    return !!current&&current.version===c.version&&current.sha256===c.sha256;
   });
   const next:Active={schemaVersion:'aive.activation.v1',releaseVersion:RELEASE,current:{...this.active.current},previous:{...(identitiesUnchanged?this.active.previous:this.active.current)}};
   for(const c of selected) {
    const source=staged.get(c.id); if(source) {
     // Newly prepared bytes always use the canonical root, never an old binding.
     const target=this.canonicalRoot(c); await this.assertActivationRoot(target); await fs.mkdir(path.dirname(target),{recursive:true});
     if(!await this.normalRoot(path.dirname(target))) throw new Error('IMMUTABLE_VERSION_CONFLICT');
     try { await fs.rename(source,target); }
     catch(error) {
      const code=(error as NodeJS.ErrnoException).code;
      if(process.platform==='win32'&&code==='EPERM') {
       // Windows also reports occupied-directory rename collisions as EPERM.
       // Do not turn a permission failure at an absent target into a collision.
       const occupied=await fs.lstat(target).then(()=>true,cause=>{if((cause as NodeJS.ErrnoException).code==='ENOENT') return false;throw cause;});
       if(!occupied) throw error;
      } else if(code!=='EEXIST'&&code!=='ENOTEMPTY') throw error;
      if(!await this.normalRoot(target)) throw new Error('IMMUTABLE_VERSION_CONFLICT');
      const marker=await readJson<{sha256?:string;version?:string}|null>(path.join(target,'.verified.json'),null);
      if(marker?.sha256!==c.sha256||marker.version!==c.version) throw new Error('IMMUTABLE_VERSION_CONFLICT');
     }
     this.legacyRoots.delete(this.identity(c));
    }
    next.current[c.id]={version:c.version,sha256:c.sha256}; const state=states.find(s=>s.id===c.id)!; state.installed=true; state.phase='ready';
   }
   await atomic(path.join(this.paths.state,'active.json'),next); this.active=next; journal.completedWork=totalWork; await update('starting'); this.publish({canCancel:false});
  } catch(error) { const cancelled=signal.aborted; journal.phase=cancelled?'cancelled':'error'; await atomic(path.join(this.paths.state,'preparation.json'),journal); this.publish({phase:journal.phase,canCancel:false,canRetry:true,error:{code:cancelled?'PREPARATION_CANCELLED':error instanceof Error?error.message:'PREPARATION_FAILED',message:cancelled?'Preparation was cancelled. Verified downloads are retained for retry.':'Component preparation failed. Open diagnostics or retry. Your existing components and projects are preserved.',retryable:true}}); throw error; }
  finally { await fs.rm(staging,{recursive:true,force:true}); this.busy=false; this.abort=null; }
 }
 private async acquire(c:ComponentManifest,signal:AbortSignal,progress:(bytes:number)=>void):Promise<string> {
  const part=confined(this.paths.cache,c.id+'-'+c.version+'-'+c.sha256+'.part');
  const stat=await fs.stat(part).catch(()=>null); if(stat?.size===c.sizeBytes && await hash(part,signal)===c.sha256) { progress(c.sizeBytes); return part; }
  for(const folder of this.offline) { const source=confined(folder,c.archive); const found=await fs.stat(source).catch(()=>null); if(found) { if(found.size!==c.sizeBytes) throw new Error('OFFLINE_COMPONENT_SIZE'); let bytes=0; await pipeline(createReadStream(source),new Transform({transform(chunk,_encoding,callback){bytes+=chunk.length;progress(bytes);callback(null,chunk);}}),createWriteStream(part,{flags:'w'}),{signal}); await fs.rm(part+'.json',{force:true}); return part; } }
  if(!c.url) throw new Error('COMPONENT_SOURCE_UNAVAILABLE');
  const saved=await readJson<{etag?:string;url?:string}>(part+'.json',{}); let offset=stat?.size??0; if(offset>c.sizeBytes||!saved.etag||saved.url!==c.url) offset=0;
  let response=await download(c.url,offset,saved.etag,signal);
  const range=response.headers['content-range']; const etag=response.headers.etag;
  if(offset>0 && (response.statusCode!==206||typeof range!=='string'||!new RegExp('^bytes '+offset+'-'+(c.sizeBytes-1)+'/'+c.sizeBytes+'$').test(range)||etag!==saved.etag)) { response.destroy(); offset=0; response=await download(c.url,0,undefined,signal); }
  if(response.statusCode!==200 && !(offset>0&&response.statusCode===206)) { response.destroy(); throw new Error('COMPONENT_HTTP_STATUS'); }
  const expected=c.sizeBytes-offset; const length=response.headers['content-length']; if(length!==undefined && Number(length)!==expected) {response.destroy();throw new Error('COMPONENT_HTTP_LENGTH');}
  await atomic(part+'.json',{etag:response.headers.etag,url:c.url}); let bytes=offset; progress(bytes);
  await pipeline(response,new Transform({transform(chunk,_encoding,callback){bytes+=chunk.length;if(bytes>c.sizeBytes)callback(new Error('COMPONENT_SIZE_EXCEEDED'));else{progress(bytes);callback(null,chunk);}}}),createWriteStream(part,{flags:offset?'a':'w'}),{signal}); if(bytes!==c.sizeBytes) throw new Error('COMPONENT_INCOMPLETE'); return part;
 }
}
function download(url:string,offset:number,etag:string|undefined,signal:AbortSignal,redirects=0,origin=new URL(url).origin):Promise<import('node:http').IncomingMessage> {
 return new Promise((resolve,reject) => { const target=new URL(url); if(target.protocol!=='https:'||target.origin!==origin||target.username||target.password||redirects>3) return reject(new Error('DOWNLOAD_REDIRECT_REJECTED'));
  const request=https.get(target,{headers:offset?{Range:`bytes=${offset}-`,'If-Range':etag!}: {},signal},response => { if([301,302,303,307,308].includes(response.statusCode??0)) {response.resume();if(!response.headers.location)return reject(new Error('DOWNLOAD_REDIRECT_INVALID'));download(new URL(response.headers.location,target).href,offset,etag,signal,redirects+1,origin).then(resolve,reject);}else resolve(response); }); request.setTimeout(30000,()=>request.destroy(new Error('DOWNLOAD_TIMEOUT')));request.on('error',reject);
 });
}
export function extract(archive:string,root:string,expandedBytes:number,signal:AbortSignal):Promise<void> {
 return new Promise((resolve,reject) => { yauzl.open(archive,{lazyEntries:true,autoClose:true,validateEntrySizes:true},(error,zip) => { if(error||!zip)return reject(error??new Error('ZIP_OPEN_FAILED')); let expanded=0;let count=0; const abort=()=>{zip.close();reject(new Error('EXTRACTION_CANCELLED'));};signal.addEventListener('abort',abort,{once:true});const fail=(error:unknown)=>{zip.close();signal.removeEventListener('abort',abort);reject(error);};zip.on('error',fail);zip.on('end',()=>{signal.removeEventListener('abort',abort);resolve();});
  zip.on('entry',entry => { void(async()=>{signal.throwIfAborted();if(++count>100000)throw new Error('ARCHIVE_ENTRY_LIMIT');const name=entry.fileName; const isDir=name.endsWith('/'); const safe=isDir?name.slice(0,-1):name; const mode=(entry.externalFileAttributes>>>16)&0xf000; if(!relative(safe)||mode===0xa000||(mode!==0&&mode!==0x8000&&mode!==0x4000)||safe==='.verified.json')throw new Error('ARCHIVE_UNSAFE_ENTRY');const file=confined(root,safe);expanded+=entry.uncompressedSize;if(expanded>expandedBytes)throw new Error('ARCHIVE_EXPANSION_LIMIT');if(isDir){await fs.mkdir(file,{recursive:true});zip.readEntry();return;}await fs.mkdir(path.dirname(file),{recursive:true});const stream=await new Promise<import('node:stream').Readable>((resolve,reject)=>zip.openReadStream(entry,(err,stream)=>err||!stream?reject(err):resolve(stream)));await pipeline(stream,createWriteStream(file,{flags:'wx'}),{signal});zip.readEntry();})().catch(fail); });zip.readEntry();
 }); });
}
async function command(executable:string,args:string[],signal:AbortSignal,stdoutOnly=false,deadlineMs=20000):Promise<string> {
 signal.throwIfAborted();
 return new Promise((resolve,reject)=>{
  const child=spawn(executable,args,{cwd:path.dirname(executable),shell:false,windowsHide:true,stdio:['ignore','pipe','pipe']});
  let output='';let received=0;let failure:Error|null=null;let settled=false;
  const cleanup=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);};
  const stop=(error:Error)=>{if(settled||failure)return;failure=error;if(child.pid&&child.exitCode===null&&child.signalCode===null){try{child.kill('SIGKILL');}catch{/* Retain ownership until close even if termination fails. */}}};
  const abort=()=>stop(new Error('PROBE_CANCELLED'));
  const timer=setTimeout(()=>stop(new Error('PROBE_TIMEOUT')),deadlineMs);
  signal.addEventListener('abort',abort,{once:true});
  const collect=(chunk:Buffer,include=true)=>{
   const remaining=Math.max(0,1024*1024-received);received+=chunk.length;
   if(include&&remaining>0)output+=chunk.subarray(0,remaining).toString('utf8');
   if(received>1024*1024)stop(new Error('PROBE_OUTPUT_LIMIT'));
  };
  child.stdout.on('data',collect);child.stderr.on('data',(chunk:Buffer)=>collect(chunk,!stdoutOnly));
  child.stdout.once('error',error=>stop(error));child.stderr.once('error',error=>stop(error));
  child.once('error',error=>{
   if(settled)return;
   if(!child.pid){settled=true;cleanup();reject(error);}else stop(error);
  });
  // close includes the owned process and both stdio streams. Never reject at
  // timeout/abort/exit while a pipe or the child can still use staging files.
  child.once('close',code=>{
   if(settled)return;settled=true;cleanup();
   if(failure)reject(failure);else if(signal.aborted)reject(new Error('PROBE_CANCELLED'));else if(code!==0)reject(new Error('PROBE_FAILED'));else resolve(output);
  });
  if(signal.aborted)abort();
 });
}
async function probe(c:ComponentManifest,root:string,signal:AbortSignal):Promise<void> {
 for(const p of c.probes) {
  const executable=confined(root,c.entrypoints[p.entrypoint]);const stat=await fs.lstat(executable);if(!stat.isFile()||stat.isSymbolicLink())throw new Error('PROBE_ENTRY_INVALID');
  if(p.kind==='whisper-model') { const runtime=confined(root,c.entrypoints[p.runtimeEntrypoint!]); const audio=confined(root,c.entrypoints[p.audioEntrypoint!]); for(const file of [runtime,audio]) { const item=await fs.lstat(file); if(!item.isFile()||item.isSymbolicLink()) throw new Error('WHISPER_PROBE_ENTRY_INVALID'); } const output=await command(runtime,['-ng','-t','4','-l','en','-m',executable,'-f',audio,'-nt','-np'],signal,true,300000); const normalize=(text:string)=>text.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim(); if(!normalize(output).includes(normalize(p.expectedText!))) throw new Error('WHISPER_TRANSCRIPTION_PROBE_FAILED'); continue; }
  if(p.kind==='engine-self-test'){const result=JSON.parse(await command(executable,['--self-test'],signal));if(result.schemaVersion!=='desktop.engine-self-test.v1'||result.status!=='ok'||result.component!==c.id||result.version!==c.version||result.frozen!==true)throw new Error('ENGINE_PROBE_IDENTITY');}
  else if(p.kind==='filter-codec-check'){const filters=await command(executable,['-hide_banner','-filters'],signal);const encoders=await command(executable,['-hide_banner','-encoders'],signal);if(!['ass','drawtext','scale','crop','overlay','concat','amix'].every(f=>new RegExp('\\b'+f+'\\b').test(filters))||!['libx264','aac'].every(f=>new RegExp('\\b'+f+'\\b').test(encoders)))throw new Error('FFMPEG_CAPABILITY_MISSING');}
  else {const args=p.kind==='whisper-runtime'?['--help']:p.kind==='document-tool-version'?['--version']:['-version'];const output=await command(executable,args,signal);const expected=p.kind==='ffmpeg-version'?'ffmpeg version':p.kind==='ffprobe-version'?'ffprobe version':p.kind==='document-tool-version'?'LibreOffice':'whisper';if(!output.toLowerCase().includes(expected.toLowerCase()))throw new Error('PROBE_UNEXPECTED_OUTPUT');}
 }
}



