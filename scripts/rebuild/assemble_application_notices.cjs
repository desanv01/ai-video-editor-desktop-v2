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
    if (!['--inventory','--output-dir','--supplements'].includes(argv[i]) || args[argv[i]] || !argv[i+1] || argv[i+1].startsWith('--')) throw Error('Usage: node assemble_application_notices.cjs --inventory PATH --output-dir FRESH_PATH [--supplements MANIFEST]');
    args[argv[i]]=argv[i+1];
  }
  if(!args['--inventory'] || !args['--output-dir']) throw Error('Both --inventory and --output-dir are required');
  return args;
}
// Typed checks cover retained identities and mechanical markers, not licensing scope.
function typedObject(v, required, optional=[]) {
  if(!v || typeof v!=='object' || Array.isArray(v) || required.some(k=>!Object.hasOwn(v,k)) ||
     Object.keys(v).some(k=>!required.includes(k) && !optional.includes(k))) throw Error('Invalid typed supplement fields');
}
const gitId=v=>typeof v==='string' && /^[a-f0-9]{40}$/.test(v);
const nonempty=v=>typeof v==='string' && !!v.trim();
function typedRelative(v) {
  return typeof v==='string' && /^[A-Za-z0-9._/-]+$/.test(v) && !path.isAbsolute(v) &&
    !v.split('/').some(p=>!p || p==='.' || p==='..');
}
function typedRepository(v) {
  if(typeof v!=='string' || !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(v) ||
     v.slice(19).split('/').some(p=>p==='.' || p==='..')) throw Error('Invalid typed source repository');
  return v.slice('https://github.com/'.length);
}
function typedPinnedSource(v, slug, commit, directory=false) {
  typedObject(v,['commit','sourcePath','url'],['gitBlob']);
  if(!gitId(v.commit) || (commit && v.commit!==commit) || !typedRelative(v.sourcePath) ||
     (v.gitBlob!==undefined && !gitId(v.gitBlob))) throw Error('Invalid pinned source identity');
  const expected=directory ? 'https://github.com/'+slug+'/tree/'+v.commit+'/'+v.sourcePath :
    'https://raw.githubusercontent.com/'+slug+'/'+v.commit+'/'+v.sourcePath;
  if(v.url!==expected) throw Error('Source URL/repository/revision/path mismatch');
}
function typedPackageProvenance(v,pkg) {
  typedObject(v,['registryMetadata','tarball','verificationQualification']);
  typedObject(v.registryMetadata,['url','sha256','publishedGitHead']);
  typedObject(v.tarball,['url','sha256','sizeBytes','distIntegrity']);
  const r=v.registryMetadata,t=v.tarball, name=pkg.name.split('/').pop();
  if(r.url!=='https://registry.npmjs.org/'+encodeURIComponent(pkg.name)+'/'+encodeURIComponent(pkg.version) ||
     !validHash(r.sha256) || !(r.publishedGitHead===null || gitId(r.publishedGitHead)) ||
     t.url!=='https://registry.npmjs.org/'+pkg.name+'/-/'+name+'-'+pkg.version+'.tgz' ||
     !validHash(t.sha256) || !validSize(t.sizeBytes) || !t.sizeBytes ||
     typeof t.distIntegrity!=='string' || !/^sha512-[A-Za-z0-9+/]{86}==$/.test(t.distIntegrity) ||
     Buffer.from(t.distIntegrity.slice(7),'base64').length!==64 ||
     Buffer.from(t.distIntegrity.slice(7),'base64').toString('base64')!==t.distIntegrity.slice(7) ||
     !nonempty(v.verificationQualification)) throw Error('Invalid recorded archive/registry provenance');
  // The assembler does not read or newly verify upstream tarball/registry bytes.
}
function typedRevision(v,slug,pkg,published) {
  if(!v || typeof v!=='object') throw Error('Missing typed revision');
  if(v.kind==='published-git-head') {
    typedObject(v,['kind','publishedGitHead','commit']);
    if(!gitId(v.commit) || v.commit!==v.publishedGitHead || v.publishedGitHead!==published) throw Error('Published gitHead mismatch');
  } else if(v.kind==='version-tag') {
    typedObject(v,['kind','publishedGitHead','tag','tagRefUrl','tagObjectSha','tagObjectUrl','commit','versionWitness','qualification']);
    if(v.publishedGitHead!==null || published!==null || !gitId(v.commit) || !gitId(v.tagObjectSha) ||
       v.tag!==pkg.name+'@'+pkg.version ||
       v.tagRefUrl!=='https://api.github.com/repos/'+slug+'/git/ref/tags/'+encodeURIComponent(v.tag) ||
       v.tagObjectUrl!=='https://api.github.com/repos/'+slug+'/git/tags/'+v.tagObjectSha ||
       !nonempty(v.qualification)) throw Error('Invalid annotated version-tag binding');
    const z=v.versionWitness;
    typedObject(z,['name','version','declaredLicense','sha256','sizeBytes','source']);
    if(z.name!==pkg.name || z.version!==pkg.version || z.declaredLicense!==pkg.license ||
       !validHash(z.sha256) || !validSize(z.sizeBytes) || !z.sizeBytes || z.sizeBytes>LIMIT) throw Error('Version witness/package mismatch');
    typedPinnedSource(z.source,slug,v.commit);
    if(path.posix.basename(z.source.sourcePath)!=='package.json') throw Error('Version witness must identify package.json');
  } else throw Error('Unknown typed revision kind');
  return v.commit;
}
function typedGrantMarkers(raw,license,attribution=false) {
  // Temporary inspection copy only; original raw bytes are always emitted.
  const text=raw.toString('utf8').replace(/\s+/g,' ').toLowerCase();
  const markers=attribution ? ['copyright','licensed under the apache license, version 2.0'] :
    license==='MIT' ? ['copyright','permission is hereby granted','above copyright notice','software is provided','as is'] :
    license==='Apache-2.0' ? ['apache license','version 2.0','grant of copyright license','redistribution','disclaimer of warranty','end of terms and conditions'] : null;
  if(!markers || markers.some(m=>!text.includes(m))) throw Error('Missing mechanical full-grant/attribution markers');
}
function typedSupplement(item,pkg,base) {
  typedObject(item,['name','version','declaredLicense','packageJsonPath','packageJsonSha256','packageJsonSizeBytes','evidenceType','provenance','files']);
  if(!/^(?:@[A-Za-z0-9._-]+\/)?[A-Za-z0-9._-]+$/.test(item.name) || !nonempty(item.version) ||
     !['MIT','Apache-2.0'].includes(item.declaredLicense) || !Array.isArray(item.files)) throw Error('Invalid typed package/evidence');
  typedObject(item.provenance,['sourceRepository','revisionBinding','package','evidenceSources','associationQualification']);
  const p=item.provenance,slug=typedRepository(p.sourceRepository);
  if(!nonempty(p.associationQualification)) throw Error('Missing association qualification');
  typedPackageProvenance(p.package,pkg);
  const commit=typedRevision(p.revisionBinding,slug,pkg,p.package.registryMetadata.publishedGitHead);
  let roles;
  if(item.evidenceType==='source-license-file' || item.evidenceType==='source-readme-full-mit-grant') {
    roles=[item.evidenceType==='source-license-file'?'source-license-file':'source-readme-full-text'];
    if(item.evidenceType==='source-readme-full-mit-grant' && pkg.license!=='MIT') throw Error('README grant type requires MIT');
    typedObject(p.evidenceSources,['notice']);
    typedPinnedSource(p.evidenceSources.notice,slug,commit);
    const name=path.posix.basename(p.evidenceSources.notice.sourcePath);
    if(item.evidenceType==='source-license-file' ? !/^licen[sc]e(?:[._-].*)?$/i.test(name) :
       !/^readme(?:[._-].*)?$/i.test(name)) throw Error('Evidence type/source path mismatch');
  } else if(item.evidenceType==='license-text-with-source-application-notices') {
    roles=['complete-license-text','source-application-notices'];
    if(pkg.license!=='Apache-2.0') throw Error('Application-notice pair requires Apache-2.0');
    typedObject(p.evidenceSources,['terms','applicationNotices','maintainerExplanationUrl']);
    typedPinnedSource(p.evidenceSources.terms,slug,null);
    if(path.posix.basename(p.evidenceSources.terms.sourcePath)!=='LICENSE' ||
       !gitId(p.evidenceSources.terms.gitBlob)) throw Error('Invalid complete-terms source');
    typedPinnedSource(p.evidenceSources.applicationNotices,slug,commit,true);
    const prefix='https://github.com/'+slug+'/issues/',url=p.evidenceSources.maintainerExplanationUrl;
    if(typeof url!=='string' || !url.startsWith(prefix) || !/^[0-9]+#issuecomment-[0-9]+$/.test(url.slice(prefix.length))) throw Error('Invalid maintainer URL');
  } else throw Error('Unknown typed evidence kind');
  if(item.files.length!==roles.length || new Set(item.files.map(f=>f.file)).size!==roles.length ||
     !roles.every(role=>item.files.filter(f=>f.kind===role).length===1)) throw Error('Typed evidence role/cardinality mismatch');
  const notices=[],inputs=[];
  for(const n of [...item.files].sort((a,b)=>cmp(a.file,b.file))) {
    typedObject(n,['kind','file','sha256','sizeBytes']);
    if(!typedRelative(n.file) || !validHash(n.sha256) || !validSize(n.sizeBytes) || !n.sizeBytes ||
       n.sizeBytes>LIMIT) throw Error('Invalid typed notice identity/path');
    const file=guarded(path.resolve(base,n.file),'file');
    if(!inside(base,file)) throw Error('Typed notice escapes manifest folder');
    const bytes=readBounded(file);
    if(bytes.length!==n.sizeBytes || hash(bytes)!==n.sha256) throw Error('Typed notice bytes/SHA mismatch');
    typedGrantMarkers(bytes,pkg.license,n.kind==='source-application-notices');
    inputs.push({file,bytes});
    notices.push({kind:n.kind,file:n.file,sizeBytes:bytes.length,sha256:n.sha256});
  }
  return {record:{name:pkg.name,version:pkg.version,declaredLicense:pkg.license,packageJsonPath:pkg.packageJsonPath,
    packageJsonSha256:pkg.packageJsonSha256,packageJsonSizeBytes:pkg.packageJsonSizeBytes,
    evidenceType:item.evidenceType,provenance:p,notices,
    evidenceCheckQualification:'Mechanical markers and recorded identities only; no licensing scope or fresh upstream/archive verification.'},inputs};
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
  // Supplements are separate upstream evidence, never fictional ASAR capture.
  const supplementInputs=[], supplementalBlobs=new Map(), supplemented=new Map();
  let supplementIdentity;
  let typedSupplementManifest=false;
  if(args['--supplements']) {
    const manifestPath=guarded(args['--supplements'],'file');
    const base=guarded(path.dirname(manifestPath),'directory');
    if(inside(base,output) || inside(output,base)) throw Error('Supplement/output overlap rejected');
    const bytes=readBounded(manifestPath), manifest=JSON.parse(bytes.toString('utf8'));
    if(manifest.schema==='aive.application-notice-supplements.v2') {
      typedObject(manifest,['schema','packages']);
      if(!Array.isArray(manifest.packages) || !manifest.packages.length) throw Error('Empty typed manifest');
      typedSupplementManifest=true;
      supplementInputs.push({file:manifestPath,bytes});
      supplementIdentity={sizeBytes:bytes.length,sha256:hash(bytes)};
      for(const item of [...manifest.packages].sort((a,b)=>cmp(a.packageJsonPath,b.packageJsonPath))) {
        const pkg=packages.find(p=>p.packageJsonPath===item.packageJsonPath);
        if(!pkg || pkg.notices.length || supplemented.has(item.packageJsonPath) ||
           pkg.name!==item.name || pkg.version!==item.version || pkg.license!==item.declaredLicense ||
           pkg.packageJsonSha256!==item.packageJsonSha256 || pkg.packageJsonSizeBytes!==item.packageJsonSizeBytes ||
           !validHash(item.packageJsonSha256) || !validSize(item.packageJsonSizeBytes)) throw Error('Typed owner identity mismatch/duplicate');
        const selected=typedSupplement(item,pkg,base);
        supplemented.set(item.packageJsonPath,selected.record);
        for(const input of selected.inputs) {
          supplementInputs.push(input);
          const digest=hash(input.bytes);
          if(supplementalBlobs.has(digest) && !supplementalBlobs.get(digest).equals(input.bytes)) throw Error('Repeated typed blob differs');
          supplementalBlobs.set(digest,input.bytes);
        }
      }
    } else {
    if(manifest.schema!=='aive.application-notice-supplements.v1' || !Array.isArray(manifest.packages) || !manifest.packages.length) throw Error('Invalid supplement manifest');
    supplementInputs.push({file:manifestPath,bytes});
    supplementIdentity={sizeBytes:bytes.length,sha256:hash(bytes)};
    for(const item of [...manifest.packages].sort((a,b)=>cmp(a.packageJsonPath,b.packageJsonPath))) {
      const pkg=packages.find(p=>p.packageJsonPath===item.packageJsonPath);
      if(!pkg || pkg.notices.length || supplemented.has(item.packageJsonPath) ||
         pkg.name!==item.name || pkg.version!==item.version || pkg.license!==item.declaredLicense ||
         pkg.packageJsonSha256!==item.packageJsonSha256 || pkg.packageJsonSizeBytes!==item.packageJsonSizeBytes ||
         !validHash(item.packageJsonSha256) || !validSize(item.packageJsonSizeBytes)) throw Error('Supplement package identity mismatch/duplicate');
      if(!item.provenance || typeof item.provenance!=='object' ||
         !/^[a-f0-9]{40}$/.test(item.provenance.packageGitHead || '') ||
         !/^[a-f0-9]{40}$/.test(item.provenance.fullTermsGitBlob || '') ||
         !validHash(item.provenance.tarballSha256) ||
         !['fullTermsUrl','sourceNoticesUrl','maintainerExplanationUrl'].every(key=>
           typeof item.provenance[key]==='string' && item.provenance[key].startsWith('https://github.com/')) ||
         typeof item.provenance.association!=='string' || !item.provenance.association.trim() ||
         !Array.isArray(item.files) || item.files.length!==2 ||
         new Set(item.files.map(f=>f.file)).size!==2 ||
         !['attribution','full-license'].every(kind=>item.files.filter(f=>f.kind===kind).length===1)) throw Error('Supplement requires full terms, attribution and provenance');
      const notices=[];
      for(const notice of [...item.files].sort((a,b)=>cmp(a.file,b.file))) {
        if(typeof notice.file!=='string' || !/^[A-Za-z0-9._/-]+$/.test(notice.file) || path.isAbsolute(notice.file) ||
           notice.file.split(/[\\/]/).some(part=>!part || part==='.' || part==='..') ||
           !validHash(notice.sha256) || !validSize(notice.sizeBytes) || notice.sizeBytes===0 || notice.sizeBytes>LIMIT) throw Error('Invalid supplemental file identity/path');
        const file=guarded(path.resolve(base,notice.file),'file');
        if(!inside(base,file)) throw Error('Supplement escapes manifest folder');
        const raw=readBounded(file);
        if(raw.length!==notice.sizeBytes || hash(raw)!==notice.sha256) throw Error('Supplement bytes/SHA mismatch');
        supplementInputs.push({file,bytes:raw});
        supplementalBlobs.set(notice.sha256,raw);
        notices.push({kind:notice.kind,file:notice.file,sizeBytes:raw.length,sha256:notice.sha256});
      }
      supplemented.set(item.packageJsonPath,{name:pkg.name,version:pkg.version,packageJsonPath:pkg.packageJsonPath,
        packageJsonSha256:pkg.packageJsonSha256,packageJsonSizeBytes:pkg.packageJsonSizeBytes,
        provenance:item.provenance,notices});
    }
    }
  }
  const unresolvedNoticeInputs=missing.filter(p=>!supplemented.has(p.packageJsonPath));
  const chunks=[];
  const append=text=>chunks.push(Buffer.from(text,'utf8'));
  if(supplementIdentity) append('THIRD-PARTY APPLICATION NOTICES\n\nActual ASAR-captured notices and separately matched upstream supplements. Release approved: false.\nNo license compliance or corresponding-source completeness determination.\n\n');
  else append('THIRD-PARTY APPLICATION NOTICES\n\nCaptured actual selected application payload only. Release approved: false.\nMissing notices remain unresolved. This assembly does not determine license compliance or corresponding-source completeness.\n\n');
  append('PACKAGE INVENTORY INDEX\n');
  for(const pkg of packages) {
    append(json({name:pkg.name,version:pkg.version,packagePath:pkg.packagePath,declaredLicense:pkg.license??null,noticeStatus:pkg.notices.length?'captured':supplemented.has(pkg.packageJsonPath)?'upstream-supplemented; no ASAR-captured notice':'UNRESOLVED: no captured notice',noticeSha256:[...new Set(pkg.notices.map(n=>n.sha256))].sort(cmp)})+'\n');
  }
  if(supplementIdentity) append('\nASAR-CAPTURE MISSING NOTICES (historical capture gaps)\n');
  else append('\nUNRESOLVED MISSING NOTICES\n');
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
  if(supplementIdentity) {
    append('\nUPSTREAM SUPPLEMENTAL NOTICES (not captured from ASAR)\n');
    for(const entry of supplemented.values()) append('MATCHED PACKAGE '+json(entry)+'\n');
    for(const digest of [...supplementalBlobs.keys()].sort(cmp)) {
      const bytes=supplementalBlobs.get(digest);
      append('\n=== UPSTREAM SUPPLEMENT '+digest+' ('+bytes.length+' raw bytes) ===\nBEGIN EXACT UPSTREAM BYTES\n');
      chunks.push(bytes);
      append('\nEND EXACT UPSTREAM BYTES\n');
    }
    append('\nUNRESOLVED NOTICE INPUTS AFTER MATCHED SUPPLEMENTS\n');
    for(const entry of unresolvedNoticeInputs) append(json(entry)+'\n');
    if(!unresolvedNoticeInputs.length) append('None reported by this input set; no compliance approval inferred.\n');
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
  if(supplementIdentity) {
    record.schema='aive.application-notices-assembly.v2';
    record.scope='Selected captured inventory plus exact package-matched upstream supplements; captured inventory gaps retained; no compliance/source/release approval.';
    record.inputs.upstreamSupplements=supplementIdentity;
    record.supplementalNoticeBlobs=supplementalBlobs.size;
    record.supplementedPackages=[...supplemented.values()];
    record.unresolvedNoticeInputs=unresolvedNoticeInputs;
  }
  if(typedSupplementManifest) {
    record.schema='aive.application-notices-assembly.v3';
    record.status='assembled-matched-upstream-inputs';
    record.inputs.upstreamSupplements.schema='aive.application-notice-supplements.v2';
    record.evidenceValidationQualification='Typed retained inputs; mechanical markers and recorded linkage only. No new upstream/archive authenticity, licensing scope, corresponding-source or release determination.';
  }
  for(const selected of supplementInputs) if(!readBounded(selected.file).equals(selected.bytes)) throw Error('Supplement input changed during assembly');
  if(!fs.readFileSync(guarded(input,'file')).equals(inventoryBytes)) throw Error('Inventory changed during assembly');
  guarded(output,undefined,true);
  fs.mkdirSync(output);
  fs.writeFileSync(path.join(output,'THIRD_PARTY_APPLICATION_NOTICES.txt'),noticeBytes,{flag:'wx'});
  fs.writeFileSync(path.join(output,'notice-assembly.json'),JSON.stringify(stable(record),null,2)+'\n',{flag:'wx'});
  if(typedSupplementManifest) console.log(JSON.stringify({status:record.status,outputDir:output,packageRecords:packages.length,capturedNoticeBlobs:blobs.size,rawCaptureGaps:missing.length,supplementedPackages:supplemented.size,supplementalNoticeBlobs:supplementalBlobs.size,unresolved:unresolvedNoticeInputs.length,releaseApproved:false}));
  else console.log(JSON.stringify({status:record.status,outputDir:output,packageRecords:packages.length,capturedNoticeBlobs:blobs.size,unresolved:missing.length,releaseApproved:false}));
}
try { main(); } catch(error) { console.error('Notice assembly failed; inputs and any partial output preserved; no retry: '+error.stack); process.exitCode=1; }