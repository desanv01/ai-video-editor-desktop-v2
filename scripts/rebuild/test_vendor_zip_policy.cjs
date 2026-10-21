// Pure source-policy check: selected TS functions only, with in-memory I/O mocks.
// No Components module import, app, native process, network, ZIP file or disk write.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {EventEmitter}=require('node:events'),{createRequire}=require('node:module');
const root=path.resolve(process.argv[2]||path.join(__dirname,'../..'));
const ts=process.argv[3]?require(path.resolve(process.argv[3])):createRequire(path.join(root,'desktop/package.json'))('typescript');
const source=fs.readFileSync(path.join(root,'desktop/electron/components.ts'),'utf8');
const util=fs.readFileSync(path.join(root,'desktop/electron/util.ts'),'utf8');
function select(text,file,names) {
 const tree=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true);
 assert.equal(tree.parseDiagnostics.length,0,'TypeScript parse errors: '+file);
 return tree.statements.filter(n=>ts.isFunctionDeclaration(n)&&names.includes(n.name?.text)||ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>names.includes(d.name.getText(tree)))).map(n=>n.getText(tree)).join('\n');
}
const componentCode=select(source,'components.ts',['kinds','validateManifest','validateDownloadOrigins','archivePath','download','extract']);
const utilCode=select(util,'util.ts',['relative','confined']);
select(fs.readFileSync(path.join(root,'contracts/rebuild/desktop.ts'),'utf8'),'desktop.ts',[]);
const compiled=ts.transpileModule(utilCode+'\n'+componentCode+'\nglobalThis.api={validateManifest,download,extract};', {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},reportDiagnostics:true});
assert.equal(compiled.diagnostics.length,0);
function harness({responses=[],entries=[]}={}) {
 const requests=[],writes=new Map(),directories=[],zipStats={closed:false,opened:false};let responseIndex=0;
 const sandbox={exports:{},URL,AbortController,AbortSignal,Set,Map,Number,Error,RELEASE:'2.1.0-rebuild.2',path:path.win32,
  https:{get(url,options,callback){requests.push({url:url.href,headers:options.headers,signal:options.signal});const request=new EventEmitter();request.setTimeout=()=>{};request.destroy=()=>{};queueMicrotask(()=>callback({statusCode:200,headers:{},resume(){},...responses[responseIndex++]}));return request;}},
  fs:{async mkdir(file){directories.push(file);}},
  createWriteStream(file,options){assert.equal(options.flags,'wx');return {file};},
  async pipeline(stream,dest,options){options.signal.throwIfAborted();const key=dest.file.toLowerCase();assert.equal(writes.has(key),false);writes.set(key,stream.text||'fixture');},
  yauzl:{open(archive,options,callback){assert.equal(options.lazyEntries,true);assert.equal(options.validateEntrySizes,true);zipStats.opened=true;const zip=new EventEmitter();let i=0;zip.close=()=>{zipStats.closed=true;};zip.readEntry=()=>queueMicrotask(()=>{if(zipStats.closed)return;if(i<entries.length)zip.emit('entry',entries[i++]);else zip.emit('end');});zip.openReadStream=(entry,cb)=>cb(null,{text:entry.text});queueMicrotask(()=>callback(null,zip));}}
 };
 vm.runInNewContext(compiled.outputText,sandbox,{filename:'selected-component-policy-only.js'});
 return {...sandbox.api,requests,writes,directories,zipStats};
}
const component={id:'ffmpeg',version:'1.2.3',archive:'ffmpeg.zip',sha256:'a'.repeat(64),sizeBytes:10,expandedBytes:100,required:true,entrypoints:{ffmpeg:'bin/ffmpeg.exe'},probes:[{kind:'ffmpeg-version',entrypoint:'ffmpeg'}],url:'https://vendor.example/versioned.zip'};
const manifest=c=>({schemaVersion:'aive.components.v1',releaseVersion:'2.1.0-rebuild.2',platform:'win32',architecture:'x64',components:[{...component,...c}]});
const entry=(fileName,uncompressedSize=1,mode=0)=>({fileName,uncompressedSize,externalFileAttributes:(mode<<16)>>>0,text:'fixture'});
let cases=0;
async function run(name,action){await action();cases++;}
(async()=>{
 await run('legacy manifest and explicit canonical origins',()=>{const h=harness();h.validateManifest(manifest({}));h.validateManifest(manifest({downloadOrigins:['https://vendor.example','https://cdn.example:8443'],archiveRoot:'vendor-1.2.3'}));});
 for(const origins of [null,[],['http://vendor.example'],['https://vendor.example/'],['https://vendor.example/path'],['https://vendor.example?'],['https://vendor.example#'],['https://user:pass@vendor.example'],['https://*.example'],['https://VENDOR.example'],['https://vendor.example:443'],['https://vendor.example','https://vendor.example'],['https://cdn.example'],Array(9).fill('https://vendor.example'),'https://vendor.example',[123]]) {
  await run('invalid origin policy '+JSON.stringify(origins),()=>assert.throws(()=>harness().validateManifest(manifest({downloadOrigins:origins})),/MANIFEST_DOWNLOAD_ORIGINS_INVALID/));
 }
 await run('origin policy without source URL',()=>assert.throws(()=>harness().validateManifest(manifest({url:undefined,downloadOrigins:['https://vendor.example']})),/MANIFEST_DOWNLOAD_ORIGINS_INVALID/));
 for(const prefix of ['',null,'../vendor','vendor/','/vendor','vendor\\root','vendor/.','vendor//root','vendor/.VERIFIED.JSON','vendor/CON','vendor/trailing.','vendor/name?']) {
  await run('invalid prefix '+JSON.stringify(prefix),()=>assert.throws(()=>harness().validateManifest(manifest({archiveRoot:prefix})),/MANIFEST_ARCHIVE_ROOT_INVALID/));
 }
 await run('same-origin default with relative redirect and range continuity',async()=>{const h=harness({responses:[{statusCode:302,headers:{location:'/pinned.zip'}},{statusCode:206}]});await h.download(component.url,4,'etag',new AbortController().signal);assert.equal(h.requests.length,2);assert.equal(h.requests[1].url,'https://vendor.example/pinned.zip');assert.deepEqual(h.requests.map(r=>r.headers.Range),['bytes=4-','bytes=4-']);assert.deepEqual(h.requests.map(r=>r.headers['If-Range']),['etag','etag']);});
 await run('explicit CDN redirect allowed',async()=>{const h=harness({responses:[{statusCode:307,headers:{location:'https://cdn.example/archive.zip?token=fixed'}}]});await h.download(component.url,0,undefined,new AbortController().signal,['https://vendor.example','https://cdn.example']);assert.equal(h.requests.length,2);});
 for(const location of ['https://cdn.example/file.zip','https://vendor.example.evil.test/file.zip','http://vendor.example/file.zip','https://user:pass@vendor.example/file.zip','https://vendor.example/file.zip#fragment','https://evil.example/file.zip']) {
  await run('reject redirect '+location,async()=>{const h=harness({responses:[{statusCode:302,headers:{location}}]});await assert.rejects(h.download(component.url,0,undefined,new AbortController().signal),/DOWNLOAD_REDIRECT_REJECTED/);assert.equal(h.requests.length,1);});
 }
 await run('malformed redirect rejects without uncaught callback',async()=>{const h=harness({responses:[{statusCode:302,headers:{location:'https://['}}]});await assert.rejects(h.download(component.url,0,undefined,new AbortController().signal),/DOWNLOAD_REDIRECT_INVALID/);});
 await run('redirect cap preserved',async()=>{const h=harness({responses:Array(5).fill({statusCode:302,headers:{location:'/loop'}})});await assert.rejects(h.download(component.url,0,undefined,new AbortController().signal),/DOWNLOAD_REDIRECT_REJECTED/);assert.equal(h.requests.length,4);});
 async function extract(entries,prefix,limit=100){const h=harness({entries});await h.extract('mock.zip','C:\\stage',limit,new AbortController().signal,prefix);return h;}
 await run('vendor sentinel stripped and nested file prepared',async()=>{const h=await extract([entry('vendor/',0,0x4000),entry('vendor/bin/',0,0x4000),entry('vendor/bin/ffmpeg.exe',7,0x8000)],'vendor');assert.deepEqual([...h.writes.keys()],['c:\\stage\\bin\\ffmpeg.exe']);assert.equal(h.directories.includes('C:\\stage\\vendor'),false);});
 await run('root sentinel optional and explicit directory may follow implicit one',async()=>{const h=await extract([entry('vendor/bin/ffmpeg.exe'),entry('vendor/bin/',0)],'vendor');assert.equal(h.writes.size,1);});
 await run('legacy ZIP layout retained',async()=>{const h=await extract([entry('bin/ffmpeg.exe')],undefined);assert.equal(h.writes.size,1);});
 for(const name of ['other/bin/tool.exe','vendor-extra/bin/tool.exe','vendor','vendor/../tool.exe','vendor//tool.exe','vendor\\tool.exe','/vendor/tool.exe','vendor/.verified.json','vendor/.VERIFIED.JSON','vendor/bin/../tool.exe','vendor/CON','vendor/bin/tool.exe.']) {
  await run('unsafe/outside prefix '+name,async()=>{const h=harness({entries:[entry(name)]});await assert.rejects(h.extract('mock.zip','C:\\stage',100,new AbortController().signal,'vendor'),/ARCHIVE_(UNSAFE_ENTRY|ROOT_MISMATCH)/);assert.equal(h.writes.size,0);});
 }
 for(const bad of [entry('vendor/link',1,0xa000),entry('vendor/file',1,0x4000),entry('vendor/dir/',1,0x8000),entry('vendor/file',-1),entry('vendor/file',Number.MAX_SAFE_INTEGER+1)]) {
  await run('unsafe entry type/size',async()=>{const h=harness({entries:[bad]});await assert.rejects(h.extract('mock.zip','C:\\stage',100,new AbortController().signal,'vendor'),/ARCHIVE_UNSAFE_ENTRY/);assert.equal(h.writes.size,0);});
 }
 for(const entries of [[entry('vendor/bin/tool.exe'),entry('vendor/BIN/TOOL.EXE')],[entry('vendor/bin'),entry('vendor/bin/tool.exe')],[entry('vendor/bin/tool.exe'),entry('vendor/bin')],[entry('vendor/',0),entry('vendor/',0)],[entry('vendor/bin/',0),entry('vendor/bin/',0)]]) {
  await run('duplicate or file/directory collision',async()=>{const h=harness({entries});await assert.rejects(h.extract('mock.zip','C:\\stage',100,new AbortController().signal,'vendor'),/ARCHIVE_DUPLICATE_ENTRY/);assert.equal(h.zipStats.closed,true);});
 }
 await run('discarded sentinel still consumes expansion budget',async()=>{const h=harness({entries:[entry('vendor/',101)]});await assert.rejects(h.extract('mock.zip','C:\\stage',100,new AbortController().signal,'vendor'),/ARCHIVE_EXPANSION_LIMIT/);assert.equal(h.writes.size,0);});
 await run('all original entries counted against entry cap',async()=>{const entries=Array.from({length:100001},(_,i)=>entry('vendor/d'+i+'/',0));const h=harness({entries});await assert.rejects(h.extract('mock.zip','C:\\stage',100,new AbortController().signal,'vendor'),/ARCHIVE_ENTRY_LIMIT/);assert.equal(h.writes.size,0);});
 await run('already cancelled extraction does not open ZIP',async()=>{const h=harness(),a=new AbortController();a.abort();await assert.rejects(h.extract('mock.zip','C:\\stage',100,a.signal,'vendor'));assert.equal(h.zipStats.opened,false);});
 await run('runtime options wired through original acquisition/extraction paths',()=>{assert.ok(source.includes('download(c.url,offset,saved.etag,signal,c.downloadOrigins)'));assert.ok(source.includes('download(c.url,0,undefined,signal,c.downloadOrigins)'));assert.ok(source.includes('extract(archive,target,c.expandedBytes,signal,c.archiveRoot)'));});
 console.log(JSON.stringify({status:'PASS',cases,scope:'selected source functions with in-memory HTTPS/ZIP/filesystem mocks',targetModuleImported:false,network:false,nativeOrAppExecution:false,build:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
