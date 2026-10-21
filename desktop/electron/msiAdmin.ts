import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

export type NativeSettlement = 'not-started' | 'normal-close' | 'ambiguous';
export class MsiAdminError extends Error {
 readonly retainStaging = true;
 constructor(code:string, readonly retainedStaging:string, readonly nativeSettlement:NativeSettlement) { super(code); this.name='MsiAdminError'; }
}
function samePath(a:string,b:string):boolean { return path.resolve(a).toLowerCase()===path.resolve(b).toLowerCase(); }
async function normalPath(file:string,kind:'file'|'directory'):Promise<void> {
 for(let current=file,first=true;;current=path.dirname(current),first=false) {
  const item=await fs.lstat(current);
  if(item.isSymbolicLink()||!(first&&kind==='file'?item.isFile():item.isDirectory())||!samePath(await fs.realpath(current),current)) throw new Error('MSI_OUTPUT_LINK_OR_TYPE');
  if(path.dirname(current)===current) break;
 }
}
// No abort signal, timeout, kill, taskkill, shell, elevated launch, or process
// discovery is attached to this native window. Only its exact close settles it.
function runMsiAdmin(executable:string,source:string,target:string,log:string,staging:string,signal:AbortSignal):Promise<void> {
 return new Promise((resolve,reject)=>{
  if(signal.aborted) { reject(new MsiAdminError('MSI_PREPARATION_CANCELLED',staging,'not-started'));return; }
  let child:ReturnType<typeof spawn>;
  try { child=spawn(executable,['/a',source,'/qn','/norestart','REBOOT=ReallySuppress','TARGETDIR='+target,'/L*v',log],{cwd:path.dirname(source),shell:false,windowsHide:true,stdio:'ignore'}); }
  catch { reject(new MsiAdminError('MSI_SPAWN_FAILED',staging,'not-started')); return; }
  let ownedPid=child.pid; let ambiguous=false; let settled=false;
  child.once('spawn',()=>{ownedPid=child.pid;});
  child.once('error',()=>{
   if(settled) return;
   if(!ownedPid) { settled=true;reject(new MsiAdminError('MSI_SPAWN_FAILED',staging,'not-started')); }
   else ambiguous=true; // A PID-bearing error still waits for owned close.
  });
  child.once('close',(code,nativeSignal)=>{
   if(settled) return; settled=true;
   if(typeof ownedPid!=='number'||!Number.isSafeInteger(ownedPid)||ownedPid<=0||ambiguous||nativeSignal!==null||!Number.isSafeInteger(code)||code===null||code<0) { reject(new MsiAdminError('MSI_NATIVE_SETTLEMENT_AMBIGUOUS',staging,'ambiguous'));return; }
   if(code!==0) { reject(new MsiAdminError('MSI_ADMIN_EXIT_'+code,staging,'normal-close'));return; }
   if(signal.aborted) { reject(new MsiAdminError('MSI_PREPARATION_CANCELLED',staging,'normal-close'));return; }
   resolve();
  });
 });
}
async function validateMsiTree(root:string,expandedBytes:number,entrypoints:readonly string[],safeRelative:(value:unknown)=>value is string,signal:AbortSignal):Promise<void> {
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
}
export async function prepareMsiAdmin(archive:string,staging:string,expandedBytes:number,entrypoints:readonly string[],safeRelative:(value:unknown)=>value is string,signal:AbortSignal):Promise<void> {
 let nativeSettlement:NativeSettlement='not-started';
 try {
 signal.throwIfAborted();
 if(process.platform!=='win32') throw new MsiAdminError('MSI_WINDOWS_REQUIRED',staging,'not-started');
 const systemRoot=process.env.SystemRoot;
 if(!systemRoot||!path.isAbsolute(systemRoot)||path.resolve(systemRoot).toLowerCase()!==systemRoot.toLowerCase()) throw new MsiAdminError('MSI_SYSTEM_ROOT_INVALID',staging,'not-started');
 const executable=path.join(systemRoot,'System32','msiexec.exe'),target=path.join(staging,'documents'),work=path.join(staging,'.msi-documents');
 await normalPath(staging,'directory');await normalPath(executable,'file');await normalPath(target,'directory');
 if((await fs.readdir(target)).length!==0) throw new MsiAdminError('MSI_TARGET_NOT_EMPTY',staging,'not-started');
 await fs.mkdir(work); // Exclusive, app-private reservation; no existing owner reused.
 const source=path.join(work,'supplier.msi'),log=path.join(work,'administrative-image.log');
 await fs.copyFile(archive,source,constants.COPYFILE_EXCL);
 signal.throwIfAborted();
 nativeSettlement='ambiguous';
 await runMsiAdmin(executable,source,target,log,staging,signal);
 nativeSettlement='normal-close';
 // Validate the actual fixed TARGETDIR image. No heuristic search or relocation.
 await validateMsiTree(target,expandedBytes,entrypoints,safeRelative,signal);
 } catch(error) {
  if(error instanceof MsiAdminError) throw error;
  throw new MsiAdminError(error instanceof Error?error.message:'MSI_PREPARATION_FAILED',staging,nativeSettlement);
 }
}
