import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { readMszipMember } from './msvcCab';
export const MSVC_PACKAGE_SHA256='843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c';
const PACKAGE_BYTES=18731856,MAX=128*1024*1024;
const NAMES=['MSVCP140.dll','VCRUNTIME140.dll','VCRUNTIME140_1.dll','MSVCP140_ATOMIC_WAIT.dll','VCOMP140.dll'] as const;
type RuntimeName=typeof NAMES[number];
export interface CabStep { offset:number; bytes:number; member:string; memberBytes:number }
export interface SupplierFile { name:RuntimeName; bytes:number; sha256:string; steps:CabStep[] }
export interface MsvcSupplierBinding { schema:'aive.msvc-private-source.v1'; packageSha256:string; packageBytes:number; files:SupplierFile[] }
// Exact five AMD64 members observed by the SAME product parser on supplier843068.
// Direct supplier data preparation; no VS licence-status implementation gate.
export const MSVC_SUPPLIER_BINDING:MsvcSupplierBinding|null={
  "schema": "aive.msvc-private-source.v1",
  "packageSha256": "843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c",
  "packageBytes": 18731856,
  "files": [
    {
      "name": "MSVCP140.dll",
      "bytes": 643512,
      "sha256": "7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca",
      "steps": [
        {
          "offset": 630000,
          "bytes": 18091661,
          "member": "a4",
          "memberBytes": 1065893
        },
        {
          "offset": 0,
          "bytes": 1065893,
          "member": "msvcp140.dll_amd64",
          "memberBytes": 643512
        }
      ]
    },
    {
      "name": "VCRUNTIME140.dll",
      "bytes": 178616,
      "sha256": "d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7",
      "steps": [
        {
          "offset": 630000,
          "bytes": 18091661,
          "member": "a4",
          "memberBytes": 1065893
        },
        {
          "offset": 0,
          "bytes": 1065893,
          "member": "vcruntime140.dll_amd64",
          "memberBytes": 178616
        }
      ]
    },
    {
      "name": "VCRUNTIME140_1.dll",
      "bytes": 50112,
      "sha256": "a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e",
      "steps": [
        {
          "offset": 630000,
          "bytes": 18091661,
          "member": "a4",
          "memberBytes": 1065893
        },
        {
          "offset": 0,
          "bytes": 1065893,
          "member": "vcruntime140_1.dll_amd64",
          "memberBytes": 50112
        }
      ]
    },
    {
      "name": "MSVCP140_ATOMIC_WAIT.dll",
      "bytes": 57792,
      "sha256": "3d0cbfaa1bf3eecf5a3f4491d2960ee803cb994f30292c6adc4a07c498f60e2b",
      "steps": [
        {
          "offset": 630000,
          "bytes": 18091661,
          "member": "a4",
          "memberBytes": 1065893
        },
        {
          "offset": 0,
          "bytes": 1065893,
          "member": "msvcp140_atomic_wait.dll_amd64",
          "memberBytes": 57792
        }
      ]
    },
    {
      "name": "VCOMP140.dll",
      "bytes": 212920,
      "sha256": "95d4ce4a6802d1e18b5e0e1722cc30ea72ca7e033f83828f05c0b7b993fe7cbf",
      "steps": [
        {
          "offset": 630000,
          "bytes": 18091661,
          "member": "a4",
          "memberBytes": 1065893
        },
        {
          "offset": 0,
          "bytes": 1065893,
          "member": "vcomp140.dll_amd64",
          "memberBytes": 212920
        }
      ]
    }
  ]
};
function need(x:unknown,m:string):asserts x {if(!x)throw new Error(m);}
const digest=(b:Buffer)=>createHash('sha256').update(b).digest('hex');
function binding(value:unknown=MSVC_SUPPLIER_BINDING):MsvcSupplierBinding {
 const b=value as MsvcSupplierBinding;
 need(b&&b.schema==='aive.msvc-private-source.v1'&&b.packageSha256===MSVC_PACKAGE_SHA256&&b.packageBytes===PACKAGE_BYTES,'MSVC_SUPPLIER_MAPPING_PENDING');
 need(Array.isArray(b.files)&&b.files.length===NAMES.length&&new Set(b.files.map(f=>f.name)).size===NAMES.length,'MSVC_SUPPLIER_FILES');let total=0;
 for(const f of b.files) {
  need(NAMES.includes(f.name)&&Number.isSafeInteger(f.bytes)&&f.bytes>0&&f.bytes<=8*1024*1024&&/^[a-f0-9]{64}$/.test(f.sha256),'MSVC_SUPPLIER_FILE');total+=f.bytes;
  need(Array.isArray(f.steps)&&f.steps.length>0&&f.steps.length<=3,'MSVC_SUPPLIER_STEPS');
  for(const s of f.steps)need(Number.isSafeInteger(s.offset)&&s.offset>=0&&Number.isSafeInteger(s.bytes)&&s.bytes>0&&s.bytes<=MAX&&Number.isSafeInteger(s.memberBytes)&&s.memberBytes>0&&s.memberBytes<=MAX&&/^[A-Za-z0-9_. -]{1,255}$/.test(s.member)&&!['.','..'].includes(s.member),'MSVC_SUPPLIER_MEMBER');
  need(f.steps[f.steps.length-1].memberBytes===f.bytes,'MSVC_SUPPLIER_MEMBER_SIZE');
 }
 need(total<=16*1024*1024,'MSVC_SUPPLIER_FILE_LIMIT');return b;
}
export function msvcSupplierConfigured():boolean {return MSVC_SUPPLIER_BINDING!==null;}
export function msvcSupplierSignature():string|null {return msvcSupplierConfigured()?digest(Buffer.from(JSON.stringify(binding()))):null;}
function supported():void {need(process.platform==='win32'&&process.arch==='x64'&&Number(os.release().split('.')[0])>=10,'MSVC_WINDOWS_10_X64_REQUIRED');}
async function normal(value:string,directory=false):Promise<void> {
 for(let current=value;;current=path.dirname(current)) {
  const s=await fs.lstat(current);need(!s.isSymbolicLink()&&(current!==value||(directory?s.isDirectory():s.isFile())),'MSVC_PATH_TYPE');
  need(path.resolve(await fs.realpath(current)).toLowerCase()===path.resolve(current).toLowerCase(),'MSVC_PATH_LINK');if(current===value&&!directory)need(s.nlink===1,'MSVC_FILE_HARDLINK');
  if(path.dirname(current)===current)break;
 }
}
export async function prepareMsvcSupplier(archive:string,target:string,signal:AbortSignal):Promise<void> {
 supported();const b=binding();await normal(archive);await normal(target,true);need((await fs.readdir(target)).length===0,'MSVC_TARGET_NOT_EMPTY');
 need((await fs.stat(archive)).size===b.packageBytes,'MSVC_PACKAGE_SIZE');const input=await fs.readFile(archive);need(digest(input)===b.packageSha256,'MSVC_PACKAGE_HASH');
 await fs.mkdir(path.join(target,'runtime'));const cache=new Map<string,Buffer>();let cachedBytes=0;
 for(const f of b.files) {
  signal.throwIfAborted();let data:Buffer=input,key='';
  for(const step of f.steps){key+=JSON.stringify(step);const prior=cache.get(key);if(prior)data=prior;else {data=readMszipMember(data,step.offset,step.bytes,step.member,step.memberBytes,signal);cachedBytes+=data.length;need(cachedBytes<=MAX,'MSVC_CACHE_LIMIT');cache.set(key,data);}}
  need(data.length===f.bytes&&digest(data)===f.sha256,'MSVC_FILE_HASH');await fs.writeFile(path.join(target,'runtime',f.name),data,{flag:'wx'});
 }
 await fs.writeFile(path.join(target,'supplier-source.json'),JSON.stringify(b,null,2)+'\n',{flag:'wx'});
}
export async function verifyPreparedMsvc(root:string,signal:AbortSignal=new AbortController().signal):Promise<boolean> {
 try {const b=binding();await normal(root,true);for(const f of b.files){signal.throwIfAborted();const p=path.join(root,'runtime',f.name);await normal(p);if((await fs.stat(p)).size!==f.bytes||digest(await fs.readFile(p))!==f.sha256)return false;}
  const record=path.join(root,'supplier-source.json');await normal(record);return JSON.stringify(JSON.parse(await fs.readFile(record,'utf8')))===JSON.stringify(b);
 }catch(error){if(signal.aborted)throw error;return false;}
}
const ENGINE:readonly [RuntimeName,string][]=[
 ['MSVCP140.dll','_internal/MSVCP140.dll'],['VCRUNTIME140.dll','_internal/VCRUNTIME140.dll'],['VCRUNTIME140_1.dll','_internal/VCRUNTIME140_1.dll'],
 ['MSVCP140.dll','_internal/numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll'],
 ['MSVCP140.dll','_internal/pyarrow.libs/msvcp140-6e7bcb4ffac2ac140bf7bcc6de529ee1.dll'],
 ['MSVCP140_ATOMIC_WAIT.dll','_internal/pyarrow.libs/msvcp140_atomic_wait-4325193497a3e8a7f3eeff01c806f206.dll']
];
const WHISPER:readonly [RuntimeName,string][]=[['MSVCP140.dll','bin/msvcp140.dll'],['VCRUNTIME140.dll','bin/vcruntime140.dll'],['VCRUNTIME140_1.dll','bin/vcruntime140_1.dll'],['VCOMP140.dll','bin/vcomp140.dll']];
function aliases(id:string):readonly [RuntimeName,string][] {need(id==='aive-engine'||id==='whisper-small','MSVC_COMPOSITION_COMPONENT');return id==='aive-engine'?ENGINE:WHISPER;}
async function noUcrt(root:string,id:string):Promise<void> {
 if(id!=='aive-engine')return;const internal=path.join(root,'_internal');await normal(internal,true);
 need(!(await fs.readdir(internal)).some(n=>n.toLowerCase()==='ucrtbase.dll'||/^api-ms-win-crt-.*\.dll$/i.test(n)),'MSVC_APP_LOCAL_UCRT_REMAINS');
}
async function policy(root:string,id:string):Promise<void> {
 const p=path.join(root,'.msvc-supplier-required.json');await normal(p);const j=JSON.parse(await fs.readFile(p,'utf8'));
 need(j.schema==='aive.external-msvc.v1'&&j.component===id&&j.minimumWindowsMajor===10&&j.packageSha256===MSVC_PACKAGE_SHA256,'MSVC_PACKAGE_REQUIRES_REPACK');
}
async function compositionParent(root:string,directory:string,signal:AbortSignal):Promise<void> {
 const base=path.resolve(root),relative=path.relative(base,path.resolve(directory));
 need(relative!==''&&relative!=='..'&&!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative),'MSVC_COMPOSITION_PARENT_ESCAPE');
 await normal(base,true);let current=base;
 for(const part of relative.split(path.sep)) {
  signal.throwIfAborted();const next=path.join(current,part);
  try {await fs.lstat(next);} catch(error) {
   if((error as NodeJS.ErrnoException).code!=='ENOENT')throw error;
   // Validate the existing owned parent before creating exactly one child.
   await normal(current,true);await fs.mkdir(next);
  }
  await normal(next,true);current=next;
 }
}
export async function composeSupplierRuntime(id:string,root:string,supplier:string,signal:AbortSignal):Promise<void> {
 supported();const b=binding();need(await verifyPreparedMsvc(supplier,signal),'MSVC_SUPPLIER_UNVERIFIED');await normal(root,true);await policy(root,id);await noUcrt(root,id);
 for(const [name,relative] of aliases(id)) {
  signal.throwIfAborted();const source=path.join(supplier,'runtime',name),destination=path.join(root,...relative.split('/'));await compositionParent(root,path.dirname(destination),signal);
  await fs.copyFile(source,destination,constants.COPYFILE_EXCL);await normal(destination);need(digest(await fs.readFile(destination))===b.files.find(f=>f.name===name)!.sha256,'MSVC_COMPOSITION_HASH');
 }
 await fs.writeFile(path.join(root,'.msvc-composition.json'),JSON.stringify({schema:'aive.msvc-composition.v1',component:id,packageSha256:b.packageSha256,bindingSha256:msvcSupplierSignature()},null,2)+'\n',{flag:'wx'});
}
export async function verifyMsvcComposition(id:string,root:string,supplier:string):Promise<boolean> {
 try {const b=binding();if(!await verifyPreparedMsvc(supplier))return false;await normal(root,true);await policy(root,id);await noUcrt(root,id);const p=path.join(root,'.msvc-composition.json');await normal(p);const m=JSON.parse(await fs.readFile(p,'utf8'));
  if(m.schema!=='aive.msvc-composition.v1'||m.component!==id||m.packageSha256!==b.packageSha256||m.bindingSha256!==msvcSupplierSignature())return false;
  for(const [name,relative] of aliases(id)){const f=b.files.find(x=>x.name===name)!;const file=path.join(root,...relative.split('/'));await normal(file);if((await fs.stat(file)).size!==f.bytes||digest(await fs.readFile(file))!==f.sha256)return false;}return true;
 }catch{return false;}
}
