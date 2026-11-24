// Independently authored helper only: VM/stub consumer check, no target imports.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),{createHash}=require('node:crypto');
const root=path.resolve(process.argv[2]||path.join(__dirname,'../..'));
const desktop=path.join(root,'desktop'),helper=path.join(desktop,'vendor/aivora-deferred-value');
const read=p=>fs.readFileSync(p,'utf8'),manifest=JSON.parse(read(path.join(desktop,'package.json'))),lock=JSON.parse(read(path.join(desktop,'package-lock.json'))),packages=lock.packages;
const sandbox={module:{exports:{}},TypeError};
vm.runInNewContext(read(path.join(helper,'index.cjs')),sandbox,{filename:'independently-authored-deferred-value.cjs'});
const {Lazy}=sandbox.module.exports;let cases=0;
async function check(name,action){try{await action();cases++;}catch(e){e.message=name+': '+e.message;throw e;}}
function resolve(owner,dep){const parts=owner?owner.split('/'):[];for(let i=parts.length;i>=0;i--){const prefix=parts.slice(0,i).join('/'),key=(prefix?prefix+'/':'')+'node_modules/'+dep;if(packages[key])return key;}return null;}
(async()=>{
 await check('named constructor and deferred factory',()=>{let calls=0;const v=new Lazy(()=>{calls++;return {ok:true};});assert.equal(calls,0);const first=v.value;assert.equal(calls,1);assert.equal(v.value,first);assert.equal(calls,1);});
 for(const value of [undefined,null,false,0,''])await check('cache successful scalar '+String(value),()=>{let calls=0;const v=new Lazy(()=>{calls++;return value;});assert.equal(v.value,value);assert.equal(v.value,value);assert.equal(calls,1);});
 await check('identical pending promise for repeated/concurrent reads',async()=>{let calls=0,release;const promise=new Promise(r=>release=r),v=new Lazy(()=>{calls++;return promise;});const a=v.value,b=v.value;assert.equal(a,promise);assert.equal(a,b);release('done');assert.deepEqual(await Promise.all([a,b]),['done','done']);assert.equal(calls,1);assert.equal(v.value,promise);});
 await check('rejected promise cached without rerunning factory',async()=>{let calls=0;const rejected=Promise.reject(new Error('expected'));rejected.catch(()=>{});const v=new Lazy(()=>{calls++;return rejected;});await assert.rejects(v.value,/expected/);assert.equal(v.value,rejected);await assert.rejects(v.value,/expected/);assert.equal(calls,1);});
 await check('synchronous throw does not cache failed invocation',()=>{let calls=0;const v=new Lazy(()=>{if(++calls===1)throw new Error('retry');return 'ok';});assert.throws(()=>v.value,/retry/);assert.equal(v.value,'ok');assert.equal(v.value,'ok');assert.equal(calls,2);});
 await check('fresh instance resets independently',()=>{let calls=0;const factory=()=>++calls,a=new Lazy(factory),b=new Lazy(factory);assert.equal(a.value,1);assert.equal(b.value,2);assert.equal(a.value,1);});
 await check('stubbed consumed updater configuration/staging/cache/publisher API',async()=>{let configCalls=0,stagingCalls=0;const updater={configOnDisk:new Lazy(()=>{configCalls++;return Promise.resolve({provider:'generic',updaterCacheDirName:'cache',publisherName:'publisher'});}),stagingUserIdPromise:new Lazy(()=>{stagingCalls++;return Promise.resolve('staging-id');})};assert.equal(await updater.configOnDisk.value.then(it=>it.provider),'generic');assert.equal((await updater.configOnDisk.value).updaterCacheDirName,'cache');assert.equal((await updater.configOnDisk.value).publisherName,'publisher');assert.equal(await updater.stagingUserIdPromise.value,'staging-id');assert.equal(await updater.stagingUserIdPromise.value,'staging-id');assert.equal(configCalls,1);assert.equal(stagingCalls,1);updater.configOnDisk=new Lazy(()=>Promise.resolve({provider:'reset'}));assert.equal((await updater.configOnDisk.value).provider,'reset');});
 await check('full approved app AGPL license copied unchanged',()=>{assert.equal(createHash('sha256').update(fs.readFileSync(path.join(root,'LICENSE'))).digest('hex'),createHash('sha256').update(fs.readFileSync(path.join(helper,'LICENSE'))).digest('hex'));const p=JSON.parse(read(path.join(helper,'package.json')));assert.equal(p.name,'@aivora/deferred-value');assert.equal(p.license,'AGPL-3.0-only');});
 await check('ordinary local updater and helper with original builder consumers retained',()=>{
  const updaterName='electron-updater',helperName='@aivora/deferred-value';
  const updaterKey='node_modules/'+updaterName,helperKey='node_modules/'+helperName;
  const updater=packages[updaterKey],mapped=packages[helperKey];
  assert.deepEqual(manifest.overrides??{},{});
  for(const [name,entry,local,version,license,members] of [
   [updaterName,updater,'vendor/electron-updater','6.8.9','MIT',['package.json','LICENSE','out/AppUpdater.js','out/AppUpdater.d.ts']],
   [helperName,mapped,'vendor/aivora-deferred-value','1.0.0','AGPL-3.0-only',['package.json','LICENSE','index.cjs','index.d.ts']],
  ]){
   const selector='file:'+local;
   assert.equal(manifest.dependencies[name],selector);
   assert.equal(packages[''].dependencies[name],selector);
   assert.ok(entry,name+' lock entry missing');
   assert.ok(!entry.link&&!entry.dev,name+' must be an ordinary production node');
   assert.equal(entry.resolved,selector);
   assert.equal(entry.version,version);
   assert.equal(entry.license,license);
   const installed=path.join(fs.realpathSync(desktop),'node_modules',name);
   assert.ok(fs.lstatSync(installed).isDirectory(),name+' must be an ordinary installed directory');
   assert.equal(fs.realpathSync(installed),installed);
   for(const member of members){
    const file=path.join(installed,member);
    assert.ok(fs.lstatSync(file).isFile(),name+' installed member must be ordinary: '+member);
    assert.equal(fs.realpathSync(file),file);
    assert.deepEqual(fs.readFileSync(file),fs.readFileSync(path.join(desktop,local,member)),name+' installed member differs: '+member);
   }
   const vendorManifest=JSON.parse(read(path.join(desktop,local,'package.json')));
   assert.equal(vendorManifest.name,name);
   assert.equal(vendorManifest.version,version);
   assert.equal(vendorManifest.license,license);
   assert.deepEqual(entry.dependencies??{},vendorManifest.dependencies??{});
  }
  assert.equal(createHash('sha256').update(read(path.join(desktop,'vendor/electron-updater/LICENSE')).replace(/\r\n/g,'\n')).digest('hex'),'bed8d0ab3e6031817f775a641ff37313b0f5591bc8ba0ed79b978dafbd4231ce');
  assert.equal(updater.dependencies[helperName],'1.0.0');
  assert.equal(updater.dependencies['lazy-val'],undefined);
  assert.equal(updater.optionalDependencies?.['lazy-val'],undefined);
  assert.equal(updater.peerDependencies?.['lazy-val'],undefined);
  assert.equal(resolve(updaterKey,helperName),helperKey);
  assert.equal(packages[updaterKey+'/node_modules/lazy-val'],undefined);
  assert.equal(packages[updaterKey+'/vendor/aivora-deferred-value'],undefined);
  const implementation=read(path.join(desktop,'vendor/electron-updater/out/AppUpdater.js'));
  const declaration=read(path.join(desktop,'vendor/electron-updater/out/AppUpdater.d.ts'));
  assert.ok(implementation.includes('require("@aivora/deferred-value")'));
  assert.ok(declaration.includes('from "@aivora/deferred-value"'));
  assert.ok(!implementation.includes('"lazy-val"')&&!declaration.includes('"lazy-val"'));
  for(const parent of ['app-builder-lib','electron-builder','electron-publish']){
   assert.equal(packages['node_modules/'+parent].dev,true);
   assert.equal(packages['node_modules/'+parent].dependencies['lazy-val'],'^1.0.5');
   assert.equal(resolve('node_modules/'+parent,'lazy-val'),'node_modules/lazy-val');
  }
  const lazy=packages['node_modules/lazy-val'];
  assert.equal(lazy.dev,true);
  assert.equal(lazy.version,'1.0.5');
  assert.equal(lazy.resolved,'https://registry.npmjs.org/lazy-val/-/lazy-val-1.0.5.tgz');
  assert.equal(lazy.integrity,'sha512-0/BnGCCfyUMkBpeDgWihanIAF9JmZhHBgUhEqzvf+adhNGLoP6TaiI5oF8oyb3I45P+PcnrqihSf01M0l0G5+Q==');
 });
 await check('unused player/load-script removed while all Revideo roots remain',()=>{assert.equal(manifest.dependencies['react-player'],undefined);assert.equal(packages['node_modules/react-player'],undefined);assert.equal(packages['node_modules/load-script'],undefined);for(const name of ['2d','core','player-react','renderer','ui','vite-plugin'])assert.equal(manifest.dependencies['@revideo/'+name],'^0.10.4');});
 await check('firstparty updater flags preserved',()=>{const main=read(path.join(desktop,'electron/main.ts'));assert.ok(main.includes('autoUpdater.autoDownload=false; autoUpdater.autoInstallOnAppQuit=false;'));});
 const seen=new Set(),missing=[],unbound=[],oldPackages=[],pending=Object.keys(manifest.dependencies).map(dep=>['',dep]);
 while(pending.length){const [owner,dep]=pending.pop(),key=resolve(owner,dep);if(!key){missing.push({owner,dep});continue;}if(seen.has(key))continue;seen.add(key);let entry=packages[key],identityKey=key;if(entry.link){identityKey=entry.resolved;entry=packages[identityKey];if(!entry||!entry.name||!entry.version)unbound.push({owner,dep,link:key,resolved:identityKey,metadata:entry||null});}if(!entry)continue;if(dep==='lazy-val'||entry.name==='lazy-val'||identityKey.endsWith('node_modules/lazy-val'))oldPackages.push(identityKey);for(const child of new Set([...Object.keys(entry.dependencies||{}),...Object.keys(entry.optionalDependencies||{})]))pending.push([identityKey,child]);}
 const updaterEntry=packages['node_modules/electron-updater'],mapped=packages['node_modules/@aivora/deferred-value'];
 const mappingBound=seen.has('node_modules/electron-updater')&&seen.has('node_modules/@aivora/deferred-value')&&resolve('node_modules/electron-updater','@aivora/deferred-value')==='node_modules/@aivora/deferred-value';
 const graphPass=missing.length===0&&unbound.length===0&&oldPackages.length===0&&mappingBound;
 console.log(JSON.stringify({status:graphPass?'PASS':'BLOCKED_LOCAL_MAPPING',compatibilityStatus:'PASS',compatibilityCases:cases,productionGraph:{status:graphPass?'PASS':'BLOCKED',reachablePackageNodes:seen.size,missingEdges:missing,unboundLocalTargets:unbound,originalLazyValReached:oldPackages,updaterEntry,mappedIdentity:mapped||null,mappingBoundToActualLocalPackage:mappingBound},targetModuleImported:false,originalLazyValImplementationRead:false,network:false,nativeOrAppExecution:false}));
 if(!graphPass)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
