import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';

export type NativeSettlement = 'not-started' | 'normal-close' | 'ambiguous';
// Decimal strings are exact JSON values, never rounded Number identifiers.
export interface MsiIdentity { path:string; kind:'file'|'directory'; bytes:string; dev:string; ino:string; mtimeNs:string; ctimeNs:string }
export interface MsiEvidence {
 operationId:string; componentId:'documents'; claim:string; boundary:string;
 lineage:'pending'|'qualified'|'unknown'; preparationCancelled?:boolean;
 selectedArchive?:{sha256:string;identity:MsiIdentity};
 copy?:{exclusive:true;source:MsiIdentity;staged?:MsiIdentity;input:string};
 native?:{attempted:boolean;spawnObserved:boolean;pid:number|null;errors:number;closeObserved:boolean;code:number|null;signal:string|null;cancelled:boolean;settlement:NativeSettlement;executable:string;argv:string[]};
 endpoint?:MsiIdentity;
 layout?:{claim:'validated-relative-name-byte-size-only';root:MsiIdentity;rows:[string,number][];sha256:string};
 activation?:{status:string;reason?:string;branch?:string;before?:MsiIdentity;after?:MsiIdentity;selectedRoot?:string;linked?:boolean;activeStatePersisted?:boolean};
 failure?:string;
}
export interface MsiCapture { operationId:string; selectedArchive:{sha256:string;identity:MsiIdentity}; persist:(evidence:MsiEvidence)=>Promise<void> }
export const MSI_LINEAGE_CLAIM='Qualified staged-copy lineage in the app-owned/no-other-writer model from archive verification through copy and original native close; no Windows Installer file-object or continuous-byte attestation.';
export class MsiAdminError extends Error {
 readonly retainStaging = true;
 constructor(code:string, readonly retainedStaging:string, readonly nativeSettlement:NativeSettlement, readonly evidence?:MsiEvidence) { super(code); this.name='MsiAdminError'; }
}
function samePath(a:string,b:string):boolean { return path.resolve(a).toLowerCase()===path.resolve(b).toLowerCase(); }
async function normalPath(file:string,kind:'file'|'directory'):Promise<void> {
 for(let current=file,first=true;;current=path.dirname(current),first=false) {
  const item=await fs.lstat(current);
  if(item.isSymbolicLink()||!(first&&kind==='file'?item.isFile():item.isDirectory())||!samePath(await fs.realpath(current),current)) throw new Error('MSI_OUTPUT_LINK_OR_TYPE');
  if(path.dirname(current)===current) break;
 }
}
export function usableMsiIdentity(value:MsiIdentity|undefined):value is MsiIdentity {
 return !!value&&typeof value.path==='string'&&(value.kind==='file'||value.kind==='directory')&&
  [value.dev,value.ino].every(v=>typeof v==='string'&&/^[1-9][0-9]*$/.test(v))&&
  typeof value.bytes==='string'&&/^(0|[1-9][0-9]*)$/.test(value.bytes)&&
  [value.mtimeNs,value.ctimeNs].every(v=>typeof v==='string'&&/^(0|-?[1-9][0-9]*)$/.test(v));
}
export async function observeMsiIdentity(file:string,kind:'file'|'directory'):Promise<MsiIdentity> {
 try {
  await normalPath(file,kind); const item=await fs.lstat(file,{bigint:true});
  const exact=(v:unknown):string=>{if(typeof v==='bigint')return v.toString();if(typeof v==='number'&&Number.isSafeInteger(v))return BigInt(v).toString();throw new Error('MSI_IDENTITY_UNAVAILABLE');};
  if(item.isSymbolicLink()||!(kind==='file'?item.isFile():item.isDirectory()))throw new Error('MSI_IDENTITY_UNAVAILABLE');
  const observed:MsiIdentity={path:path.resolve(file),kind,bytes:exact(item.size),dev:exact(item.dev),ino:exact(item.ino),mtimeNs:exact(item.mtimeNs),ctimeNs:exact(item.ctimeNs)};
  if(!usableMsiIdentity(observed))throw new Error('MSI_IDENTITY_UNAVAILABLE');
  return observed;
 } catch { throw new Error('MSI_IDENTITY_UNAVAILABLE'); }
}
export function sameMsiObject(a:MsiIdentity|undefined,b:MsiIdentity|undefined):boolean {
 return usableMsiIdentity(a)&&usableMsiIdentity(b)&&a.kind===b.kind&&a.dev===b.dev&&a.ino===b.ino;
}
export function sameMsiSnapshot(a:MsiIdentity,b:MsiIdentity):boolean {
 return sameMsiObject(a,b)&&a.bytes===b.bytes&&a.mtimeNs===b.mtimeNs&&a.ctimeNs===b.ctimeNs;
}
// No abort signal, timeout, kill, taskkill, shell, elevated launch, or process
// discovery is attached to this native window. Only its exact close settles it.
function runMsiAdmin(executable:string,source:string,target:string,log:string,staging:string,signal:AbortSignal,facts?:NonNullable<MsiEvidence['native']>):Promise<void> {
 return new Promise((resolve,reject)=>{
  if(signal.aborted) { if(facts)facts.cancelled=true; reject(new MsiAdminError('MSI_PREPARATION_CANCELLED',staging,'not-started'));return; }
  let child:ReturnType<typeof spawn>;
  if(facts)facts.attempted=true;
  try { child=spawn(executable,['/a',source,'/qn','/norestart','REBOOT=ReallySuppress','TARGETDIR='+target,'/L*v',log],{cwd:path.dirname(source),shell:false,windowsHide:true,stdio:'ignore'}); }
  catch { if(facts)facts.errors++; reject(new MsiAdminError('MSI_SPAWN_FAILED',staging,'not-started')); return; }
  let ownedPid=child.pid; let ambiguous=false; let settled=false;
  if(facts)facts.pid=typeof ownedPid==='number'?ownedPid:null;
  child.once('spawn',()=>{ownedPid=child.pid;if(facts){facts.spawnObserved=true;facts.pid=typeof ownedPid==='number'?ownedPid:null;}});
  child.once('error',()=>{
   if(settled) return;
   if(facts)facts.errors++;
   if(!ownedPid) { settled=true;reject(new MsiAdminError('MSI_SPAWN_FAILED',staging,'not-started')); }
   else ambiguous=true; // A PID-bearing error still waits for owned close.
  });
  child.once('close',(code,nativeSignal)=>{
   if(settled) return; settled=true;
   if(facts){facts.closeObserved=true;facts.pid=typeof ownedPid==='number'?ownedPid:null;facts.code=code;facts.signal=nativeSignal;facts.cancelled=signal.aborted;}
   if(typeof ownedPid!=='number'||!Number.isSafeInteger(ownedPid)||ownedPid<=0||ambiguous||nativeSignal!==null||!Number.isSafeInteger(code)||code===null||code<0) { if(facts)facts.settlement='ambiguous';reject(new MsiAdminError('MSI_NATIVE_SETTLEMENT_AMBIGUOUS',staging,'ambiguous'));return; }
   if(facts)facts.settlement='normal-close';
   if(code!==0) { reject(new MsiAdminError('MSI_ADMIN_EXIT_'+code,staging,'normal-close'));return; }
   if(signal.aborted) { reject(new MsiAdminError('MSI_PREPARATION_CANCELLED',staging,'normal-close'));return; }
   resolve();
  });
 });
}
async function validateMsiTree(root:string,expandedBytes:number,entrypoints:readonly string[],safeRelative:(value:unknown)=>value is string,signal:AbortSignal):Promise<[string,number][]> {
 await normalPath(root,'directory');
 const pending=[{directory:root,relative:''}],seen=new Set<string>(),files=new Map<string,number>();let count=0;let bytes=0;
 while(pending.length) {
  signal.throwIfAborted();const current=pending.pop()!;
  for(const name of await fs.readdir(current.directory)) {
   signal.throwIfAborted();if(++count>100000) throw new Error('MSI_OUTPUT_ENTRY_LIMIT');
   const relative=current.relative?current.relative+'/'+name:name;
   if(!safeRelative(relative)||seen.has(relative.toLowerCase())) throw new Error('MSI_OUTPUT_UNSAFE_PATH');
   seen.add(relative.toLowerCase());const file=path.join(current.directory,name),info=await fs.lstat(file);
   if(info.isSymbolicLink()||(!info.isDirectory()&&!info.isFile())||!samePath(await fs.realpath(file),file)) throw new Error('MSI_OUTPUT_LINK_OR_TYPE');
   if(info.isDirectory()) pending.push({directory:file,relative});
   else {
    if(info.nlink>1||!Number.isSafeInteger(info.size)||info.size<0) throw new Error('MSI_OUTPUT_LINK_OR_TYPE');
    bytes+=info.size;if(!Number.isSafeInteger(bytes)||bytes>expandedBytes) throw new Error('MSI_OUTPUT_EXPANSION_LIMIT');
    files.set(relative,info.size);
   }
  }
 }
 for(const entry of entrypoints) if(!safeRelative(entry)||!files.has(entry)||files.get(entry)===0) throw new Error('MSI_OUTPUT_ENTRYPOINT_MISSING');
 return [...files].sort(([a],[b])=>a<b?-1:a>b?1:0);
}
export async function prepareMsiAdmin(archive:string,staging:string,expandedBytes:number,entrypoints:readonly string[],safeRelative:(value:unknown)=>value is string,signal:AbortSignal,capture?:MsiCapture):Promise<MsiEvidence|void> {
 let nativeSettlement:NativeSettlement='not-started';
 const evidence:MsiEvidence|undefined=capture?{operationId:capture.operationId,componentId:'documents',claim:MSI_LINEAGE_CLAIM,boundary:'selected',lineage:'pending',selectedArchive:capture.selectedArchive}:undefined;
 const save=async(boundary:string)=>{if(evidence&&capture){evidence.boundary=boundary;try{await capture.persist(evidence);}catch{throw new Error('MSI_EVIDENCE_PERSIST_FAILED');}}};
 try {
 signal.throwIfAborted();
 if(!capture||typeof capture.persist!=='function')throw new MsiAdminError('MSI_PRIVATE_RECEIPT_REQUIRED',staging,'not-started');
 if(process.platform!=='win32') throw new MsiAdminError('MSI_WINDOWS_REQUIRED',staging,'not-started');
 const systemRoot=process.env.SystemRoot;
 if(!systemRoot||!path.isAbsolute(systemRoot)||path.resolve(systemRoot).toLowerCase()!==systemRoot.toLowerCase()) throw new MsiAdminError('MSI_SYSTEM_ROOT_INVALID',staging,'not-started');
 const executable=path.join(systemRoot,'System32','msiexec.exe'),target=path.join(staging,'documents'),work=path.join(staging,'.msi-documents');
 await normalPath(staging,'directory');await normalPath(executable,'file');await normalPath(target,'directory');
 if((await fs.readdir(target)).length!==0) throw new MsiAdminError('MSI_TARGET_NOT_EMPTY',staging,'not-started');
 await fs.mkdir(work); // Exclusive, app-private reservation; no existing owner reused.
 const source=path.join(work,'supplier.msi'),log=path.join(work,'administrative-image.log');
 if(evidence){
  const selected=capture!.selectedArchive;
  if(!capture!.operationId||!selected||!/^([a-f0-9]{64})$/.test(selected.sha256)||!usableMsiIdentity(selected.identity))throw new Error('MSI_VERIFIED_LINEAGE_MISSING');
  const observed=await observeMsiIdentity(archive,'file');
  if(!samePath(observed.path,selected.identity.path)||!sameMsiSnapshot(observed,selected.identity))throw new Error('MSI_SELECTED_IDENTITY_CHANGED');
  evidence.copy={exclusive:true,source:observed,input:source};
 }
 await fs.copyFile(archive,source,constants.COPYFILE_EXCL);
 if(evidence){
  const staged=await observeMsiIdentity(source,'file');
  if(staged.bytes!==evidence.copy!.source.bytes)throw new Error('MSI_COPY_SIZE_CHANGED');
  if(sameMsiObject(staged,evidence.copy!.source))throw new Error('MSI_STAGED_OBJECT_NOT_DISTINCT');
  evidence.copy!.staged=staged;
  evidence.native={attempted:false,spawnObserved:false,pid:null,errors:0,closeObserved:false,code:null,signal:null,cancelled:signal.aborted,settlement:'not-started',executable,argv:['/a',source,'/qn','/norestart','REBOOT=ReallySuppress','TARGETDIR='+target,'/L*v',log]};
  await save('pre-spawn');
 }
 signal.throwIfAborted();
 nativeSettlement='ambiguous';
 let nativeError:unknown,observationError:unknown;
 try { await runMsiAdmin(executable,source,target,log,staging,signal,evidence?.native);nativeSettlement='normal-close'; }
 catch(error) { nativeError=error;if(error instanceof MsiAdminError)nativeSettlement=error.nativeSettlement; }
 if(evidence?.native)evidence.native.settlement=nativeSettlement;
 try {
  await save('native-terminal');
  if(evidence?.native?.closeObserved){
   evidence.endpoint=await observeMsiIdentity(source,'file');
   if(!sameMsiSnapshot(evidence.copy!.staged!,evidence.endpoint))throw new Error('MSI_STAGED_ENDPOINT_CHANGED');
   await save('input-endpoint');
  }
 } catch(error) { observationError=error; }
 // Observation failure never reclassifies the original close or masks its error.
 if(nativeError)throw nativeError;
 if(observationError)throw observationError;
 signal.throwIfAborted();
 if(evidence)evidence.lineage='qualified';
 // Validate the actual fixed TARGETDIR image. No heuristic search or relocation.
 const rows=await validateMsiTree(target,expandedBytes,entrypoints,safeRelative,signal);
 if(evidence){evidence.layout={claim:'validated-relative-name-byte-size-only',root:await observeMsiIdentity(target,'directory'),rows,sha256:createHash('sha256').update(JSON.stringify(rows),'utf8').digest('hex')};evidence.preparationCancelled=signal.aborted;await save('validated-layout');}
 signal.throwIfAborted();
 return evidence;
 } catch(error) {
  if(error instanceof MsiAdminError)nativeSettlement=error.nativeSettlement;
  if(evidence){
   if(evidence.native)evidence.native.settlement=nativeSettlement;
   evidence.lineage='unknown';evidence.preparationCancelled=signal.aborted;
   evidence.failure=error instanceof Error?error.message:'MSI_PREPARATION_FAILED';
   try{await save('failed');}catch{throw new MsiAdminError('MSI_EVIDENCE_PERSIST_FAILED',staging,nativeSettlement,evidence);}
  }
  throw new MsiAdminError(error instanceof Error?error.message:'MSI_PREPARATION_FAILED',staging,nativeSettlement,evidence);
 }
}
