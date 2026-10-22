import { inflateRawSync } from 'node:zlib';
const MAX=128*1024*1024;
function need(value:unknown,message:string):asserts value { if(!value)throw new Error(message); }
function inside(b:Buffer,o:number,n:number):void {need(Number.isSafeInteger(o)&&Number.isSafeInteger(n)&&o>=0&&n>=0&&o<=b.length-n,'CRT_CAB_BOUNDS');}
export interface CabMember { name:string; bytes:number; offsetInFolder:number; folder:number }
interface ParsedCab { data:Buffer; files:CabMember[]; folders:{offset:number;blocks:number;compression:number}[]; tableEnd:number }
function parseCab(source:Buffer,offset:number,size:number,signal:AbortSignal):ParsedCab {
 signal.throwIfAborted();need(size<=MAX,'CRT_CAB_SIZE_LIMIT');inside(source,offset,size);const container=source.subarray(offset,offset+size);
 need(container.length>=36&&container.subarray(0,4).toString('ascii')==='MSCF'&&container[24]===3&&container[25]===1,'CRT_CAB_UNSUPPORTED_HEADER');
 const declared=container.readUInt32LE(8),flags=container.readUInt16LE(30);let foldersAt=36;
 if(flags===0)need(declared===container.length,'CRT_CAB_UNSIGNED_LENGTH');
 else {
  // Only the observed Microsoft signed-CAB reservation shape. Whole supplier EXE
  // hash remains mandatory; this validates bounds, NOT the opaque signature.
  need(flags===4&&container.length>=60,'CRT_CAB_UNSUPPORTED_FLAGS');
  need(container.readUInt16LE(36)===20&&container[38]===0&&container[39]===0,'CRT_CAB_RESERVED_SHAPE');
  const signatureOffset=container.readUInt32LE(44),signatureBytes=container.readUInt32LE(48);
  need(container.readUInt32LE(40)===0x00100000&&declared>=60&&declared<container.length&&signatureOffset===declared&&signatureBytes===container.length-declared&&signatureBytes>0&&signatureBytes<=65536&&container.readUInt32LE(52)===0&&container.readUInt32LE(56)===0,'CRT_CAB_SIGNATURE_DESCRIPTOR');
  foldersAt=60;
 }
 // No signature bytes can be interpreted as folders, file table or MSZIP data.
 const b=container.subarray(0,declared);
 const nfolders=b.readUInt16LE(26),count=b.readUInt16LE(28);need(nfolders>0&&nfolders<=32&&count>0&&count<=10000,'CRT_CAB_COUNTS');inside(b,foldersAt,nfolders*8);
 const folders=[];
 for(let i=0;i<nfolders;i++){const at=foldersAt+i*8;folders.push({offset:b.readUInt32LE(at),blocks:b.readUInt16LE(at+4),compression:b.readUInt16LE(at+6)});}
 let cursor=b.readUInt32LE(16);need(cursor>=foldersAt+nfolders*8,'CRT_CAB_FILE_TABLE');const files:CabMember[]=[],seen=new Set<string>();
 for(let i=0;i<count;i++) {
  signal.throwIfAborted();inside(b,cursor,16);const bytes=b.readUInt32LE(cursor),start=b.readUInt32LE(cursor+4),folder=b.readUInt16LE(cursor+8);const end=b.indexOf(0,cursor+16);
  need(end>=cursor+16&&end<=cursor+271,'CRT_CAB_NAME');const name=b.subarray(cursor+16,end).toString('utf8');
  need(/^[A-Za-z0-9_. -]{1,255}$/.test(name)&&!['.','..'].includes(name)&&!seen.has(name.toLowerCase())&&folder<nfolders,'CRT_CAB_MEMBER');seen.add(name.toLowerCase());
  need(bytes<=MAX&&start<=MAX-bytes,'CRT_CAB_MEMBER_LIMIT');files.push({name,bytes,offsetInFolder:start,folder});cursor=end+1;
 }
 for(const f of folders){need(f.offset>=cursor&&f.blocks>0,'CRT_CAB_FOLDER');inside(b,f.offset,8);}
 return {data:b,files,folders,tableEnd:cursor};
}
/** Header/table metadata only. Names are data and are never used as output paths. */
export function listCabMembers(source:Buffer,offset:number,size:number,signal:AbortSignal):{files:CabMember[];folders:{offset:number;blocks:number;compression:number}[]} {
 const c=parseCab(source,offset,size,signal);return {files:c.files,folders:c.folders};
}
/** Selected data member only; no filesystem/native execution API or archive writes.
 * Caller pins the complete supplier package and each selected output SHA256.
 * Only MSZIP, single-cab, no-reserved-header format is supported; others fail closed. */
export function readMszipMember(source:Buffer,offset:number,size:number,member:string,expectedBytes:number,signal:AbortSignal):Buffer {
 const c=parseCab(source,offset,size,signal),b=c.data;const selected=c.files.find(f=>f.name===member);need(selected&&selected.bytes===expectedBytes,'CRT_CAB_SELECTED_MEMBER');
 const folder=c.folders[selected.folder];let at=folder.offset;need(folder.compression===1,'CRT_CAB_MSZIP_REQUIRED');const chunks:Buffer[]=[];let dictionary:Buffer=Buffer.alloc(0),total=0;
 for(let i=0;i<folder.blocks;i++) {
  signal.throwIfAborted();inside(b,at,8);const compressed=b.readUInt16LE(at+4),expanded=b.readUInt16LE(at+6);at+=8;
  need(compressed>=2&&expanded>0&&expanded<=32768&&total<=MAX-expanded,'CRT_CAB_BLOCK_LIMIT');inside(b,at,compressed);const chunk=b.subarray(at,at+compressed);
  need(chunk[0]===67&&chunk[1]===75,'CRT_CAB_MSZIP_SIGNATURE');const value=inflateRawSync(chunk.subarray(2),{dictionary:dictionary.length?dictionary:undefined,maxOutputLength:expanded});need(value.length===expanded,'CRT_CAB_BLOCK_SIZE');
  chunks.push(value);total+=value.length;dictionary=Buffer.concat([dictionary,value]).subarray(-32768);at+=compressed;
 }
 const data=Buffer.concat(chunks,total);inside(data,selected.offsetInFolder,selected.bytes);return Buffer.from(data.subarray(selected.offsetInFolder,selected.offsetInFolder+selected.bytes));
}
