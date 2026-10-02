'use strict';
// Main-owned focused boundary checks. These use real files/ZIP streams and HTTP,
// with Electron APIs and executable probes substituted; installed-app acceptance is separate.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const {createHash} = require('node:crypto');
const {EventEmitter} = require('node:events');
const http = require('node:http');
const os = require('node:os');
const test = require('node:test');
const root = path.resolve(process.argv[2] || path.join(__dirname,'../..'));
const compiled = path.join(root,'desktop/dist-electron/desktop/electron');
function load(name, mocks = {}) {
  const file = path.join(compiled,name+'.js');
  const module = {exports:{}};
  const actualRequire = createRequire(file);
  const context = {module,exports:module.exports,require:id=>Object.hasOwn(mocks,id)?mocks[id]:actualRequire(id),
    __dirname:path.dirname(file),__filename:file,process,Buffer,URL,Request,Response,Headers,AbortController,AbortSignal,
    setTimeout,clearTimeout,queueMicrotask,console};
  vm.runInNewContext(require('node:fs').readFileSync(file,'utf8'),context,{filename:file});
  return module.exports;
}
const util = load('util');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
function zip(entries) {
  // Independent stored-ZIP fixture writer (real central directory, CRC, Unix mode).
  const crc = data => {let c=0xffffffff;for(const b of data){c^=b;for(let j=0;j<8;j++)c=(c>>>1)^((c&1)?0xedb88320:0);}return (c^0xffffffff)>>>0;};
  const local=[],central=[];let offset=0;
  for(const entry of entries){const name=Buffer.from(entry.name),data=Buffer.from(entry.data||'pack fixture');const check=crc(data);
    const h=Buffer.alloc(30);h.writeUInt32LE(0x04034b50);h.writeUInt16LE(20,4);h.writeUInt32LE(check,14);h.writeUInt32LE(data.length,18);h.writeUInt32LE(data.length,22);h.writeUInt16LE(name.length,26);
    const c=Buffer.alloc(46);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(0x0314,4);c.writeUInt16LE(20,6);c.writeUInt32LE(check,16);c.writeUInt32LE(data.length,20);c.writeUInt32LE(data.length,24);c.writeUInt16LE(name.length,28);c.writeUInt32LE(((entry.mode||0x81a4)<<16)>>>0,38);c.writeUInt32LE(offset,42);
    local.push(h,name,data);central.push(c,name);offset+=h.length+name.length+data.length;
  }
  const directory=Buffer.concat(central),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50);end.writeUInt16LE(entries.length,8);end.writeUInt16LE(entries.length,10);end.writeUInt32LE(directory.length,12);end.writeUInt32LE(offset,16);
  return Buffer.concat([...local,directory,end]);
}
async function fixture(t){const p=await fs.mkdtemp(path.join(os.tmpdir(),'aive-phase2-main-'));t.after(()=>fs.rm(p,{recursive:true,force:true}));return p;}
let probes=0;
function probeSpawn(executable,args){probes++;const child=new EventEmitter();child.stdout=new EventEmitter();child.stderr=new EventEmitter();child.kill=()=>true;
  queueMicrotask(()=>{const text=path.basename(executable)==='engine.exe'?JSON.stringify({schemaVersion:'desktop.engine-self-test.v1',status:'ok',component:'aive-engine',version:'2.1.0-rebuild.1',frozen:true}):path.basename(executable)==='ffmpeg.exe'?'ffmpeg version fixture':'LibreOffice fixture';child.stdout.emit('data',Buffer.from(text));child.emit('exit',0);child.emit('close',0);});return child;}
const components=load('components',{'node:child_process':{spawn:probeSpawn}});
const release=()=>({schemaVersion:'aive.components.v1',releaseVersion:util.RELEASE,platform:'win32',architecture:'x64',components:[]});
function component(id,bytes,entry,kind){return {id,version:util.RELEASE,archive:id+'.zip',sha256:digest(bytes),sizeBytes:bytes.length,expandedBytes:4096,required:true,entrypoints:{tool:entry,...(id==='aive-engine'?{engine:entry}:{})},probes:[{kind,entrypoint:'tool'}]};}
test('manifest rejects incompatible identity, traversal, duplicate and missing joint model proof',()=>{
  const valid=release();valid.components=[component('aive-engine',Buffer.from('x'),'engine.exe','engine-self-test')];components.validateManifest(valid);
  for(const mutate of [m=>m.architecture='arm64',m=>m.components[0].sha256='x',m=>m.components[0].entrypoints.tool='../engine.exe',m=>m.components.push(m.components[0]),m=>m.components[0].probes=[{kind:'whisper-model',entrypoint:'tool'}]]){
    const value=structuredClone(valid);mutate(value);assert.throws(()=>components.validateManifest(value));
  }
});
test('actual ZIP extraction rejects traversal, symlink and expansion overflow',async t=>{
  const p=await fixture(t);for(const [name,entries,bound] of [['traversal',[{name:'../outside'}],100],['symlink',[{name:'link',mode:0xa1ff}],100],['overflow',[{name:'large',data:'123456'}],3]]){
    const archive=path.join(p,name+'.zip');await fs.writeFile(archive,zip(entries));const out=path.join(p,name);await fs.mkdir(out);await assert.rejects(components.extract(archive,out,bound,new AbortController().signal));
  }
  assert.equal(await fs.stat(path.join(p,'outside')).catch(()=>null),null);
});
test('all packs verify and probe before atomic publication; reopen reuses activation',async t=>{
  const p=await fixture(t),offline=path.join(p,'offline');await fs.mkdir(offline);const m=release();
  for(const [id,entry,kind] of [['aive-engine','engine.exe','engine-self-test'],['ffmpeg','ffmpeg.exe','ffmpeg-version'],['documents','soffice.exe','document-tool-version']]){
    const bytes=zip([{name:entry}]);await fs.writeFile(path.join(offline,id+'.zip'),bytes);m.components.push(component(id,bytes,entry,kind));
  }
  const manifest=path.join(p,'manifest.json');await fs.writeFile(manifest,JSON.stringify(m));const paths=await util.paths(path.join(p,'app'));const states=[];const c=new components.Components(paths,manifest,[offline],s=>states.push(s));await c.initialize();await c.prepare();assert.equal(await c.allRequiredInstalled(),true);await c.markReady();
  const count=probes,again=new components.Components(paths,manifest,[offline],()=>{});await again.initialize();assert.equal(await again.allRequiredInstalled(),true);await again.prepare();assert.equal(probes,count);
  const activation=JSON.parse(await fs.readFile(path.join(paths.state,'active.json')));assert.equal(Object.keys(activation.current).length,3);assert.equal(states.some(s=>s.phase==='ready'),false);
});
test('bad archive hash never reaches a probe or activation',async t=>{
  const p=await fixture(t),offline=path.join(p,'offline');await fs.mkdir(offline);const bytes=zip([{name:'engine.exe'}]),m=release();
  for(const [id,entry,kind] of [['aive-engine','engine.exe','engine-self-test'],['ffmpeg','ffmpeg.exe','ffmpeg-version'],['documents','soffice.exe','document-tool-version']]){const c=component(id,bytes,entry,kind);c.sha256='0'.repeat(64);m.components.push(c);await fs.writeFile(path.join(offline,id+'.zip'),bytes);}
  const manifest=path.join(p,'manifest.json');await fs.writeFile(manifest,JSON.stringify(m));const paths=await util.paths(path.join(p,'app'));const c=new components.Components(paths,manifest,[offline],()=>{});await c.initialize();const count=probes;await assert.rejects(c.prepare(),/COMPONENT_HASH_MISMATCH/);assert.equal(probes,count);assert.equal(await fs.stat(path.join(paths.state,'active.json')).catch(()=>null),null);
});
test('credential bridge rejects unknown provider and fails closed without encryption',async t=>{
  const p=await fixture(t);let available=true;const {Credentials}=load('credentials',{electron:{safeStorage:{isEncryptionAvailable:()=>available,encryptString:v=>Buffer.from(v).reverse(),decryptString:v=>Buffer.from(v).reverse().toString('utf8')}}});const c=new Credentials(p);
  assert.throws(()=>c.set('invented','secret'),/INVALID_PROVIDER/);await c.set('openai','private-value');const stored=await fs.readFile(path.join(p,'credentials.json'),'utf8');assert.equal(stored.includes('private-value'),false);assert.deepEqual(JSON.parse(JSON.stringify(await c.metadata())),[{provider:'openai',configured:true}]);available=false;await assert.rejects(c.set('mistral','secret'),/CREDENTIAL_WRITE_FAILED/);available=true;await c.remove('openai');assert.equal((await c.metadata()).length,0);
});
test('API proxy streams multipart and preserves range status/headers while replacing auth',async t=>{
  let observed;const server=http.createServer(async(req,res)=>{let size=0;for await(const b of req)size+=b.length;observed={method:req.method,auth:req.headers.authorization,range:req.headers.range,type:req.headers['content-type'],size};res.writeHead(206,{'Content-Type':'video/mp4','Content-Range':'bytes 100-109/1000','Content-Length':'10','Accept-Ranges':'bytes'});res.end('0123456789');});await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
  const {proxy,apiPath}=load('protocol',{electron:{net:{fetch}}});const abort=new AbortController();const endpoint={url:'http://127.0.0.1:'+server.address().port,token:'main-held-secret',signal:abort.signal};
  const data=new FormData();data.append('media',new Blob([Buffer.alloc(2*1024*1024,65)]),'lecture.mp4');const request=new Request('aive://app/api/v1/videos/upload',{method:'POST',body:data,headers:{Authorization:'renderer-secret',Range:'bytes=100-109'}});const result=await proxy(request,endpoint);assert.equal(result.status,206);assert.equal(result.headers.get('Content-Range'),'bytes 100-109/1000');assert.equal(await result.text(),'0123456789');assert.equal(observed.auth,'Bearer main-held-secret');assert.equal(observed.range,'bytes=100-109');assert.match(observed.type,/multipart\/form-data; boundary=/);assert.ok(observed.size>2*1024*1024);
  for(const value of ['https://other/api/v1/x','/api/v1/%2e%2e/%2e%2e/secret','/api/v1/a\\b','/api/v1/x#fragment'])assert.equal(apiPath(value),false);
  const denied=await proxy(new Request('aive://attacker/api/v1/videos'),endpoint);assert.equal(denied.status,400);
});
test('proxy cancellation invalidates an existing private transport',async t=>{
  const server=http.createServer((_req,res)=>{res.writeHead(200,{'Content-Type':'video/mp4'});res.write('first');});await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>{server.closeAllConnections();server.close();});const {proxy}=load('protocol',{electron:{net:{fetch}}});const abort=new AbortController();const response=await proxy(new Request('aive://app/api/v1/videos/x/resource'),{url:'http://127.0.0.1:'+server.address().port,token:'private',signal:abort.signal});const reader=response.body.getReader();await reader.read();abort.abort();await assert.rejects(reader.read());
});
async function supervisorFixture(t,mode){
 const p=await fixture(t),paths=await util.paths(path.join(p,'app')),helper=path.join(p,'engine-fixture.cjs');
 await fs.writeFile(helper,`const http=require('node:http'),net=require('node:net'),crypto=require('node:crypto');
 const version='2.1.0-rebuild.1'; const server=http.createServer((req,res)=>{if(req.headers.authorization!=='Bearer '+process.env.AIVE_ENGINE_BEARER_TOKEN){res.writeHead(401);res.end();return;} if(req.url==='/readiness'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({schemaVersion:'desktop.health-readiness.v1',process:{alive:true,pid:process.pid,componentId:'aive-engine',componentVersion:version},checks:{api:{state:'ready'},database:{state:'ready'}}}));}else if(req.url==='/engine-control/credentials'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({status:'applied',configuredProviders:[]}));}else if(req.url==='/engine-control/shutdown'){res.end();server.close(()=>process.exit(0));}else{res.writeHead(404);res.end();}});
 server.listen(0,'127.0.0.1',()=>{const h={type:'aive-engine-startup',protocolVersion:'desktop.engine-handshake.v2',sessionId:process.env.AIVE_ENGINE_SESSION_ID,nonce:process.env.AIVE_ENGINE_CONTROL_NONCE,pid:process.pid,componentId:'aive-engine',componentVersion:version,host:'127.0.0.1',assignedPort:server.address().port};h.hmacSha256=crypto.createHmac('sha256',process.env.AIVE_ENGINE_BEARER_TOKEN).update([h.protocolVersion,h.sessionId,h.nonce,h.pid,h.componentId,h.componentVersion,h.host,h.assignedPort].join('\\n')).digest('hex');if(process.env.FIXTURE_MODE==='forged')h.hmacSha256='0'.repeat(64);if(process.env.FIXTURE_MODE==='wrong-pid')h.pid++;const [host,port]=process.env.AIVE_ENGINE_CONTROL_ADDRESS.split(':');const socket=net.connect(+port,host,()=>{socket.end(JSON.stringify(h)+'\\n');if(process.env.FIXTURE_MODE!=='good')setTimeout(()=>process.exit(0),25);});});`);
 const children=[];const childProcess=require('node:child_process');const spawn=(exe,args,options)=>{assert.equal(options.windowsHide,true);assert.equal(options.shell,false);assert.equal(args.length,0);assert.equal(args.some(a=>a.includes(options.env.AIVE_ENGINE_BEARER_TOKEN)),false);const child=childProcess.spawn(process.execPath,[helper],{...options,env:{...options.env,FIXTURE_MODE:mode}});children.push(child);return child;};
 const {Supervisor}=load('supervisor',{electron:{net:{fetch}},'node:child_process':{spawn}});const changes=[];const supervisor=new Supervisor(paths,(state,code)=>changes.push({state,code}));t.after(async()=>{await supervisor.stop();for(const c of children)if(c.exitCode===null)c.kill();});return {supervisor,changes,paths};
}
test('private supervisor authenticates real child handshake and shuts down owned process',async t=>{
 const {supervisor,changes,paths}=await supervisorFixture(t,'good');await supervisor.start({id:'aive-engine',version:util.RELEASE,entrypoints:{engine:'engine.exe'}},paths.components,paths.components);const endpoint=supervisor.getEndpoint();assert.match(endpoint.url,/^http:\/\/127\.0\.0\.1:\d+$/);assert.equal(endpoint.token.length,64);assert.equal(changes.at(-1).state,'ready');await supervisor.stop();assert.equal(endpoint.signal.aborted,true);assert.throws(()=>supervisor.getEndpoint(),/ENGINE_NOT_READY/);assert.equal(changes.at(-1).state,'stopped');
});
test('private supervisor rejects forged HMAC and wrong child PID',async t=>{
 for(const mode of ['forged','wrong-pid']){const {supervisor,changes,paths}=await supervisorFixture(t,mode);await assert.rejects(supervisor.start({id:'aive-engine',version:util.RELEASE,entrypoints:{engine:'engine.exe'}},paths.components,paths.components),/HANDSHAKE_REJECTED/);assert.throws(()=>supervisor.getEndpoint(),/ENGINE_NOT_READY/);assert.equal(changes.at(-1).state,'failed');}
});
