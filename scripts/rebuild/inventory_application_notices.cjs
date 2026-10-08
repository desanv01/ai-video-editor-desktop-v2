'use strict';
// Source-only inventory tool. Main owns invocation, review and release acceptance.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const Module = require('node:module');
const ROOT = path.resolve('C:/Users/Dv/Desktop/ai-video-editor-standalone-release-work/rebuild');
const MAX_TEXT_BYTES = 16 * 1024 * 1024;
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function beneath(parent, child) {
  const rel = path.relative(parent, child);
  return rel === '' || (!path.isAbsolute(rel) && rel !== '..' && !rel.startsWith('..' + path.sep));
}
function guarded(value, kind, missingLeaf = false) {
  const target = path.resolve(value);
  if (!beneath(ROOT, target)) throw Error('Outside authorized rebuild root: ' + target);
  const parsed = path.parse(target);
  let current = parsed.root;
  const parts = target.slice(parsed.root.length).split(path.sep).filter(Boolean);
  for (let i = 0; i < parts.length; i++) {
    current = path.join(current, parts[i]);
    let st;
    try { st = fs.lstatSync(current); } catch (error) {
      if (missingLeaf && i === parts.length - 1 && error.code === 'ENOENT') return target;
      throw error;
    }
    if (st.isSymbolicLink()) throw Error('Symlink/junction rejected: ' + current);
    if (fs.realpathSync.native(current).toLowerCase() !== current.toLowerCase()) {
      throw Error('Reparse/alias ancestry rejected: ' + current);
    }
    if (i < parts.length - 1 && !st.isDirectory()) throw Error('Non-directory ancestry: ' + current);
  }
  const st = fs.lstatSync(target);
  if (kind === 'file' && !st.isFile()) throw Error('Nonregular input: ' + target);
  if (kind === 'directory' && !st.isDirectory()) throw Error('Not a directory: ' + target);
  return target;
}
async function identity(file) {
  guarded(file, 'file');
  const before = fs.statSync(file);
  const h = crypto.createHash('sha256');
  let sizeBytes = 0;
  for await (const chunk of fs.createReadStream(file, { highWaterMark: 256 * 1024 })) {
    h.update(chunk); sizeBytes += chunk.length;
  }
  const after = fs.statSync(file);
  if (sizeBytes !== before.size || after.size !== before.size || after.mtimeMs !== before.mtimeMs || after.ino !== before.ino) {
    throw Error('Input changed during hashing: ' + file);
  }
  return { path: file, sizeBytes, sha256: h.digest('hex') };
}
function argumentsFrom(argv) {
  const allowed = new Set(['--asar', '--asar-library', '--resources', '--output-dir']);
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!allowed.has(argv[i]) || !argv[i + 1] || argv[i + 1].startsWith('--') || args[argv[i]]) {
      throw Error('Usage: node inventory_application_notices.cjs --asar PATH --asar-library PATH --resources PATH --output-dir PATH');
    }
    args[argv[i]] = argv[i + 1];
  }
  if (Object.keys(args).length !== allowed.size) throw Error('All four CLI arguments are required');
  return args;
}
function loadLibrary(value) {
  const selected = guarded(value);
  let directory = fs.statSync(selected).isDirectory() ? selected : path.dirname(selected);
  let packageFile;
  while (beneath(ROOT, directory)) {
    const candidate = path.join(directory, 'package.json');
    if (fs.existsSync(candidate)) {
      guarded(candidate, 'file');
      const metadata = JSON.parse(fs.readFileSync(candidate, 'utf8').replace(/^\uFEFF/, ''));
      if (metadata.name === '@electron/asar') { packageFile = candidate; break; }
    }
    const parent = path.dirname(directory);
    if (parent === directory) break;
    directory = parent;
  }
  if (!packageFile) throw Error('Explicit library must belong to @electron/asar');
  const bytes = fs.readFileSync(packageFile);
  const metadata = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''));
  const entry = guarded(path.join(directory, metadata.main || 'index.js'), 'file');
  if (!beneath(directory, entry)) throw Error('Library main escapes its package');
  if (selected !== directory && selected !== entry) throw Error('Select the library package directory or its declared main file');
  // Guard all transitive non-builtin module reads during explicit library loading.
  const original = Module._load;
  Module._load = function(request, parent, isMain) {
    const resolved = Module._resolveFilename(request, parent, isMain);
    if (path.isAbsolute(resolved)) guarded(resolved, 'file');
    return original.apply(this, arguments);
  };
  let library;
  try { library = require(entry); } finally { Module._load = original; }
  for (const name of ['getRawHeader', 'extractFile']) if (typeof library[name] !== 'function') throw Error('Missing ASAR API: ' + name);
  return { library, record: { name: metadata.name, version: metadata.version, entry, packageJsonPath: packageFile, packageJsonSha256: sha(bytes) } };
}
function entriesFrom(header) {
  const entries = [];
  function visit(node, prefix) {
    if (!node || typeof node !== 'object' || 'link' in node) throw Error('ASAR link/invalid node rejected: ' + prefix);
    if (node.files) {
      for (const name of Object.keys(node.files).sort(compare)) {
        if (!name || name === '.' || name === '..' || /[\\/:\0]/.test(name)) throw Error('Unsafe ASAR entry: ' + name);
        visit(node.files[name], prefix ? prefix + '/' + name : name);
      }
    } else {
      if (!Number.isSafeInteger(node.size) || node.size < 0) throw Error('Invalid ASAR size: ' + prefix);
      entries.push({ archivePath: prefix, sizeBytes: node.size, unpacked: Boolean(node.unpacked) });
    }
  }
  visit(header, '');
  return entries;
}
function regularTree(directory) {
  const files = [];
  if (!fs.existsSync(directory)) return files;
  function walk(dir) {
    guarded(dir, 'directory');
    for (const name of fs.readdirSync(dir).sort(compare)) {
      const file = guarded(path.join(dir, name));
      const st = fs.lstatSync(file);
      if (st.isDirectory()) walk(file);
      else if (st.isFile()) files.push(file);
      else throw Error('Nonregular unpacked entry: ' + file);
    }
  }
  walk(directory);
  return files;
}
async function main() {
  const args = argumentsFrom(process.argv.slice(2));
  const archive = guarded(args['--asar'], 'file');
  const resources = guarded(args['--resources'], 'directory');
  if (archive !== path.join(resources, 'app.asar')) throw Error('--asar must be the selected resources/app.asar');
  const selectedLibrary = guarded(args['--asar-library']);
  const output = guarded(args['--output-dir'], undefined, true);
  if (fs.existsSync(output)) throw Error('Output already exists; refusing overwrite: ' + output);
  const unpacked = archive + '.unpacked';
  for (const input of [archive, resources, selectedLibrary, unpacked]) {
    if (beneath(output, input) || beneath(input, output)) throw Error('Output overlaps an input: ' + input);
  }
  guarded(path.dirname(output), 'directory');
  const { library, record: libraryRecord } = loadLibrary(selectedLibrary);
  const archiveIdentity = await identity(archive);
  const entries = entriesFrom(library.getRawHeader(archive).header);
  const physicalFiles = regularTree(unpacked);
  for (const entry of entries.filter(e => e.unpacked)) {
    const physical = guarded(path.join(unpacked, ...entry.archivePath.split('/')), 'file');
    if (fs.statSync(physical).size !== entry.sizeBytes) throw Error('Unpacked size mismatch: ' + entry.archivePath);
  }
  function read(entry) {
    if (entry.sizeBytes > MAX_TEXT_BYTES) throw Error('Selected metadata/notice exceeds 16 MiB bound: ' + entry.archivePath);
    if (entry.unpacked) guarded(path.join(unpacked, ...entry.archivePath.split('/')), 'file');
    const bytes = library.extractFile(archive, entry.archivePath.split('/').join(path.sep), false);
    if (bytes.length !== entry.sizeBytes) throw Error('Extracted size mismatch: ' + entry.archivePath);
    return bytes;
  }
  const packages = entries.filter(e => /(?:^|\/)node_modules\/(?:@[^/]+\/)?[^/]+\/package\.json$/.test(e.archivePath));
  const roots = packages.map(e => e.archivePath.slice(0, -'/package.json'.length)).sort((a,b) => b.length - a.length || compare(a,b));
  const captured = new Map();
  const inventory = packages.map(entry => {
    const bytes = read(entry);
    const pkg = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''));
    const packagePath = entry.archivePath.slice(0, -'/package.json'.length);
    return { name: pkg.name ?? null, version: pkg.version ?? null, license: pkg.license ?? pkg.licenses ?? null,
      repository: pkg.repository ?? null, packagePath, packageJsonPath: entry.archivePath,
      packageJsonSha256: sha(bytes), packageJsonSizeBytes: bytes.length, notices: [] };
  });
  const byRoot = new Map(inventory.map(p => [p.packagePath, p]));
  for (const entry of entries) {
    const basename = path.posix.basename(entry.archivePath);
    if (!/^(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?$/i.test(basename)) continue;
    const owner = roots.find(dir => entry.archivePath.startsWith(dir + '/'));
    if (!owner) continue;
    // A nested node_modules subtree without package metadata is still not parent-owned.
    if (entry.archivePath.slice(owner.length + 1).split('/').includes('node_modules')) continue;
    const bytes = read(entry), digest = sha(bytes);
    if (!captured.has(digest)) captured.set(digest, bytes);
    byRoot.get(owner).notices.push({ archivePath: entry.archivePath, sizeBytes: bytes.length, sha256: digest, captured: 'notices/' + digest + '.txt' });
  }
  inventory.sort((a,b) => compare(a.packageJsonPath,b.packageJsonPath));
  for (const pkg of inventory) { pkg.notices.sort((a,b)=>compare(a.archivePath,b.archivePath)); pkg.missingCapturedNotices = pkg.notices.length === 0; }
  const nativeBinaries = [];
  for (const file of physicalFiles.filter(f => /\.(exe|dll|node)$/i.test(f))) {
    const id = await identity(file);
    nativeBinaries.push({ resourcesPath: path.relative(resources,file).split(path.sep).join('/'), sizeBytes: id.sizeBytes, sha256: id.sha256 });
  }
  nativeBinaries.sort((a,b)=>compare(a.resourcesPath,b.resourcesPath));
  const finalIdentity = await identity(archive);
  if (finalIdentity.sha256 !== archiveIdentity.sha256) throw Error('ASAR changed during inventory');
  const record = { schema: 'aive.application-notices-inventory.v1', status: 'captured', releaseApproved: false,
    scope: 'Actual selected ASAR dependency notices and resources/app.asar.unpacked native payload only; no license approval or remote corresponding-source determination.',
    inputs: { asar: archiveIdentity, resources, asarLibrary: libraryRecord },
    limits: { metadataAndNoticeMaxBytes: MAX_TEXT_BYTES, nativeHashReadChunkBytes: 256 * 1024, missingCapturedNoticesIsConservative: true },
    packageRecords: inventory.length, capturedNoticeBlobs: captured.size,
    missingCapturedNotices: inventory.filter(p=>p.missingCapturedNotices).map(p=>({name:p.name,version:p.version,packageJsonPath:p.packageJsonPath})),
    nativeBinaries, inventory };
  // No output exists until all reads and inventory construction succeed. Never reuse prior output.
  guarded(output, undefined, true);
  fs.mkdirSync(output);
  fs.mkdirSync(path.join(output,'notices'));
  for (const digest of [...captured.keys()].sort(compare)) fs.writeFileSync(path.join(output,'notices',digest+'.txt'),captured.get(digest),{flag:'wx'});
  fs.writeFileSync(path.join(output,'inventory.json'),JSON.stringify(record,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({status:record.status,outputDir:output,packageRecords:inventory.length,capturedNoticeBlobs:captured.size,nativeBinaries:nativeBinaries.length,releaseApproved:false}));
}
main().catch(error => { console.error('Inventory failed; inputs and any partial output preserved; no retry: ' + error.stack); process.exitCode = 1; });