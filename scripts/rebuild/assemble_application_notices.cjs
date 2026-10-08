'use strict';
// Assemble only captured evidence. Main owns invocation, review and release decisions.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const DEFAULT_ROOT = 'C:/Users/Dv/Desktop/ai-video-editor-standalone-release-work/rebuild';
const configuredRoot = process.env.AIVE_REBUILD_ROOT || DEFAULT_ROOT;
if (!path.isAbsolute(configuredRoot)) throw Error('AIVE_REBUILD_ROOT must be an absolute configured rebuild root');
const ROOT = path.resolve(configuredRoot);
const LIMIT = 16 * 1024 * 1024;
const cmp = (a,b) => a < b ? -1 : a > b ? 1 : 0;
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const validHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const validSize = value => Number.isSafeInteger(value) && value >= 0;
function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith('..' + path.sep));
}
function guarded(value, type, fresh = false) {
  const full = path.resolve(value);
  if (!inside(ROOT,full)) throw Error('Path outside configured rebuild root: ' + full);
  const base = path.parse(full).root;
  let current = base;
  const pieces = full.slice(base.length).split(path.sep).filter(Boolean);
  for (let i=0; i<pieces.length; i++) {
    current = path.join(current,pieces[i]);
    let st;
    try { st=fs.lstatSync(current); } catch (e) {
      if (fresh && i===pieces.length-1 && e.code==='ENOENT') return full;
      throw e;
    }
    if (st.isSymbolicLink() || fs.realpathSync.native(current).toLowerCase() !== current.toLowerCase()) {
      throw Error('Symlink/junction/reparse ancestry rejected: ' + current);
    }
    if (i<pieces.length-1 && !st.isDirectory()) throw Error('Non-directory ancestry: '+current);
  }
  const st=fs.lstatSync(full);
  if (type==='file' && !st.isFile()) throw Error('Nonregular selected file: '+full);
  if (type==='directory' && !st.isDirectory()) throw Error('Expected directory: '+full);
  return full;
}
function readBounded(file) {
  guarded(file,'file');
  if (fs.statSync(file).size>LIMIT) throw Error('Selected text exceeds 16 MiB: '+file);
  const bytes=fs.readFileSync(file);
  if (bytes.length>LIMIT) throw Error('Selected text grew beyond limit: '+file);
  return bytes;
}
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value==='object') return Object.fromEntries(Object.keys(value).sort(cmp).map(k=>[k,stable(value[k])]));
  return value;
}
const json = value => JSON.stringify(stable(value));
function argsFrom(argv) {
  const args={};
  for(let i=0;i<argv.length;i+=2) {
    if (!['--inventory','--output-dir'].includes(argv[i]) || args[argv[i]] || !argv[i+1] || argv[i+1].startsWith('--')) throw Error('Usage: node assemble_application_notices.cjs --inventory PATH --output-dir FRESH_PATH');
    args[argv[i]]=argv[i+1];
  }
  if(Object.keys(args).length!==2) throw Error('Both --inventory and --output-dir are required');
  return args;
}
function main() {
  if(ROOT===path.parse(ROOT).root) throw Error('Filesystem root is not an approved rebuild root');
  guarded(ROOT,'directory');
  const args=argsFrom(process.argv.slice(2));
  const input=guarded(args['--inventory'],'file');
  const folder=guarded(path.dirname(input),'directory');
  const output=guarded(args['--output-dir'],undefined,true);
  if(fs.existsSync(output)) throw Error('Output already exists; refusing overwrite');
  if(inside(folder,output) || inside(output,folder)) throw Error('Input/output overlap rejected');
  guarded(path.dirname(output),'directory');
  const inventoryBytes=readBounded(input);
  const inventory=JSON.parse(inventoryBytes.toString('utf8').replace(/^\uFEFF/,''));
  if(inventory.schema!=='aive.application-notices-inventory.v1' || !Array.isArray(inventory.inventory) || !Array.isArray(inventory.missingCapturedNotices)) throw Error('Invalid inventory schema');
  if(inventory.packageRecords!==inventory.inventory.length || !validSize(inventory.capturedNoticeBlobs)) throw Error('Inventory count disagreement');
  const asar=inventory.inputs && inventory.inputs.asar;
  if(!asar || !validSize(asar.sizeBytes) || !validHash(asar.sha256)) throw Error('Invalid recorded ASAR identity');
  const packages=[...inventory.inventory].sort((a,b)=>cmp(a.packageJsonPath,b.packageJsonPath));
  const paths=new Set(), blobs=new Map(), owners=new Map(), missing=[];
  for(const pkg of packages) {
    if(typeof pkg.packagePath!=='string' || !pkg.packagePath || typeof pkg.packageJsonPath!=='string' || pkg.packageJsonPath!==pkg.packagePath+'/package.json' || paths.has(pkg.packageJsonPath) || !Array.isArray(pkg.notices)) throw Error('Invalid/duplicate package record');
    if(!validHash(pkg.packageJsonSha256) || !validSize(pkg.packageJsonSizeBytes)) throw Error('Invalid recorded package JSON identity');
    if(!(pkg.name===null || typeof pkg.name==='string') || !(pkg.version===null || typeof pkg.version==='string')) throw Error('Invalid package name/version');
    paths.add(pkg.packageJsonPath);
    if(pkg.missingCapturedNotices!==(pkg.notices.length===0)) throw Error('Missing-notice flag disagreement');
    if(!pkg.notices.length) missing.push({name:pkg.name,version:pkg.version,packageJsonPath:pkg.packageJsonPath});
    const references=new Set();
    for(const notice of [...pkg.notices].sort((a,b)=>cmp(a.archivePath,b.archivePath))) {
      if(!validHash(notice.sha256) || !validSize(notice.sizeBytes) || notice.sizeBytes>LIMIT || notice.captured!=='notices/'+notice.sha256+'.txt') throw Error('Invalid notice identity/path');
      if(typeof notice.archivePath!=='string' || !notice.archivePath.startsWith(pkg.packagePath+'/') || references.has(notice.archivePath)) throw Error('Invalid/duplicate owning notice path');
      references.add(notice.archivePath);
      const file=guarded(path.join(folder,...notice.captured.split('/')),'file');
      if(!inside(folder,file)) throw Error('Captured notice escapes inventory folder');
      const bytes=readBounded(file);
      if(bytes.length!==notice.sizeBytes || hash(bytes)!==notice.sha256) throw Error('Captured notice bytes/SHA mismatch: '+notice.captured);
      if(blobs.has(notice.sha256) && !blobs.get(notice.sha256).equals(bytes)) throw Error('Inconsistent repeated blob');
      blobs.set(notice.sha256,bytes);
      if(!owners.has(notice.sha256)) owners.set(notice.sha256,[]);
      owners.get(notice.sha256).push({name:pkg.name,version:pkg.version,packagePath:pkg.packagePath,declaredLicense:pkg.license??null,archivePath:notice.archivePath});
    }
  }
  const recordedMissing=[...inventory.missingCapturedNotices].sort((a,b)=>cmp(a.packageJsonPath,b.packageJsonPath));
  if(json(recordedMissing)!==json(missing) || blobs.size!==inventory.capturedNoticeBlobs) throw Error('Missing-list/blob-count disagreement');
  const chunks=[];
  const append=text=>chunks.push(Buffer.from(text,'utf8'));
  append('THIRD-PARTY APPLICATION NOTICES\n\nCaptured actual selected application payload only. Release approved: false.\nMissing notices remain unresolved. This assembly does not determine license compliance or corresponding-source completeness.\n\n');
  append('PACKAGE INVENTORY INDEX\n');
  for(const pkg of packages) {
    append(json({name:pkg.name,version:pkg.version,packagePath:pkg.packagePath,declaredLicense:pkg.license??null,noticeStatus:pkg.notices.length?'captured':'UNRESOLVED: no captured notice',noticeSha256:[...new Set(pkg.notices.map(n=>n.sha256))].sort(cmp)})+'\n');
  }
  append('\nUNRESOLVED MISSING NOTICES\n');
  if(!missing.length) append('None reported by the selected captured inventory; no compliance approval inferred.\n');
  for(const entry of missing) append(json(entry)+'\n');
  for(const digest of [...blobs.keys()].sort(cmp)) {
    const bytes=blobs.get(digest);
    append('\n=== CAPTURED NOTICE '+digest+' ('+bytes.length+' raw bytes) ===\n');
    for(const owner of owners.get(digest).sort((a,b)=>cmp(a.packagePath,b.packagePath)||cmp(a.archivePath,b.archivePath))) append('OWNER '+json(owner)+'\n');
    append('BEGIN EXACT CAPTURED BYTES\n');
    chunks.push(bytes); // No decoding, newline normalization or replacement of captured bytes.
    append('\nEND EXACT CAPTURED BYTES\n');
  }
  const noticeBytes=Buffer.concat(chunks);
  const nameVersions=[...new Set(packages.map(p=>json({name:p.name,version:p.version})))].sort(cmp).map(s=>JSON.parse(s));
  const record={schema:'aive.application-notices-assembly.v1',status:'assembled-captured-evidence',releaseApproved:false,
    scope:'Selected captured inventory and notice bytes only; unresolved notices explicit; no supplemental npm inputs, ASAR reads, remote-source assumptions or compliance determination.',
    inputs:{inventory:{sizeBytes:inventoryBytes.length,sha256:hash(inventoryBytes)},actualAsar:{sizeBytes:asar.sizeBytes,sha256:asar.sha256}},
    packageRecords:packages.length,uniqueNames:new Set(packages.map(p=>p.name)).size,uniqueNameVersions:nameVersions.length,nameVersions,
    capturedNoticeBlobs:blobs.size,missingCapturedNotices:missing,
    outputs:{thirdPartyApplicationNotices:{file:'THIRD_PARTY_APPLICATION_NOTICES.txt',sizeBytes:noticeBytes.length,sha256:hash(noticeBytes)}},
    qualification:'Assembly JSON does not include its own hash; immutable identity of the assembled notice text is recorded. Main owns final review and release acceptance.'};
  if(!fs.readFileSync(guarded(input,'file')).equals(inventoryBytes)) throw Error('Inventory changed during assembly');
  guarded(output,undefined,true);
  fs.mkdirSync(output);
  fs.writeFileSync(path.join(output,'THIRD_PARTY_APPLICATION_NOTICES.txt'),noticeBytes,{flag:'wx'});
  fs.writeFileSync(path.join(output,'notice-assembly.json'),JSON.stringify(stable(record),null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({status:record.status,outputDir:output,packageRecords:packages.length,capturedNoticeBlobs:blobs.size,unresolved:missing.length,releaseApproved:false}));
}
try { main(); } catch(error) { console.error('Notice assembly failed; inputs and any partial output preserved; no retry: '+error.stack); process.exitCode=1; }