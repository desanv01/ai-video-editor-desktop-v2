'use strict';
// Main-owned download boundary tests. Native save and browser DOM are substituted;
// installed save/export acceptance remains a separate gate.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const {createRequire} = require('node:module');
const root = path.resolve(process.argv[2] || path.join(__dirname, '../..'));
const dependencyRoot = path.resolve(process.argv[3] || path.join(root, 'desktop'));
const ts = createRequire(path.join(dependencyRoot, 'package.json'))('typescript');
const file = path.join(root, 'desktop/src/lib/api.ts');
const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  fileName:file, compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS}
}).outputText;
function load({native, response, saveResult=true, saveError, bridgeResponse}={}) {
  const calls={save:[],fetch:[],anchors:[],timers:[],revoked:[],bridge:[],blobs:[]};
  class TestURL extends URL {
    static createObjectURL(blob){calls.blobs.push(blob);return 'blob:download-fixture';}
    static revokeObjectURL(url){calls.revoked.push(url);}
  }
  const window={location:{href:native?'aive://app/index.html':'http://localhost:5173/'},
    setTimeout(fn,ms){calls.timers.push({fn,ms});return calls.timers.length;},clearTimeout(){}};
  if(native) window.aiveDesktop={async saveResource(apiPath,name){calls.save.push({path:apiPath,name});if(saveError)throw saveError;return saveResult;}};
  const document={body:{appendChild(anchor){anchor.appended=true;}},createElement(tag){assert.equal(tag,'a');const anchor={click(){this.clicked=true;},remove(){this.removed=true;}};calls.anchors.push(anchor);return anchor;}};
  const module={exports:{}};
  const context={exports:module.exports,module,window,document,URL:TestURL,Headers,Request,Response,FormData,Blob,AbortController,DOMException,TextEncoder,Uint8Array,atob,btoa,
    fetch:async(url,options)=>{calls.fetch.push({url,options});if(!response)throw new Error('Unexpected fetch');return response();},
    require(id){assert.equal(id,'@tauri-apps/api/core');return {invoke:async(name,payload)=>{calls.bridge.push({name,payload});return bridgeResponse;}};}};
  vm.runInNewContext(compiled,context,{filename:file});return {api:module.exports,calls};
}
test('Electron saves all four original formats using the existing bridge without fetch or blob DOM',async()=>{
  const {api,calls}=load({native:true});
  const id='07db0367-a27b-4b27-8940-6cfd1577682a';
  for(const [format,name] of [['txt','original_transcript.txt'],['timestamped_txt','original_transcript_timestamped.txt'],['json','original_transcript.json'],['csv','original_transcript_segments.csv']]) {
    assert.equal(await api.downloadOriginalTranscript(id,format),true);
    assert.deepEqual(calls.save.at(-1),{path:`/api/v1/videos/${id}/transcript/export?format=${format}`,name});
  }
  assert.equal(calls.fetch.length,0);assert.equal(calls.anchors.length,0);assert.equal(calls.blobs.length,0);
});
test('Electron cancellation remains false; save failures and invalid bridge results give actionable errors',async()=>{
  const cancelled=load({native:true,saveResult:false});assert.equal(await cancelled.api.downloadEngineResource('/api/v1/videos/a/download','lecture.mp4'),false);
  for(const config of [{saveError:new Error('secret process detail')},{saveResult:undefined}]) {
    // Explicit invalid result avoids the fixture default parameter.
    const instance=load({native:true,...config,saveResult:config.saveError?true:null});
    await assert.rejects(instance.api.downloadEngineResource('/api/v1/videos/a/download','lecture.mp4'),e=>e.code==='DOWNLOAD_SAVE_FAILED'&&!e.message.includes('secret'));
  }
});
test('Electron rejects foreign URLs and non-engine paths before save; safe Unicode suggestions stay bounded',async()=>{
  const {api,calls}=load({native:true});
  for(const url of ['https://evil.test/api/v1/videos/a/download','http://localhost:8000/api/v1/videos/a/download','//evil.test/api/v1/videos/a/download','aive://other/api/v1/x','aive://user:pass@app/api/v1/x','aive://app:123/api/v1/x','aive://app/api/v1/x#fragment','/assets/file','bridge://engine-resource/videos/a/download','/api/v1/../../private']) {
    await assert.rejects(api.downloadEngineResource(url,'name'),e=>e.code==='DOWNLOAD_URL_REJECTED');
  }
  assert.equal(calls.save.length,0);
  await api.downloadEngineResource('aive://app/api/v1/videos/a/download?token=public','讲义/😀:*?'.repeat(40)+' .');
  const name=calls.save[0].name;
  assert.ok(name.includes('讲义'));assert.ok(name.includes('😀'));assert.ok(name.length<=180);assert.ok(!/[\\/:*?"<>|\x00-\x1f\x7f]/.test(name));assert.ok(!/[. ]$/.test(name));assert.ok(!/[\uD800-\uDBFF]$/.test(name));
  await api.downloadEngineResource('/api/v1/videos/a/download','..');assert.equal(calls.save[1].name,'export');
});
test('Browser normalizes the API prefix once and honors Unicode attachment names without claiming completed saves',async()=>{
  const {api,calls}=load({response:()=>new Response('text',{headers:{'Content-Disposition':"attachment; filename*=UTF-8''%E8%AE%B2%E4%B9%89.txt"}})});
  for(const resource of ['/api/v1/videos/a/download?format=txt','http://localhost:8000/api/v1/videos/a/download?format=txt']) {
    assert.equal(await api.downloadEngineResource(resource,'fallback.txt'),true);
    assert.equal(calls.fetch.at(-1).url,'http://localhost:8000/api/v1/videos/a/download?format=txt');
    const anchor=calls.anchors.at(-1);assert.equal(anchor.download,'讲义.txt');assert.ok(anchor.appended&&anchor.clicked&&anchor.removed);
  }
  assert.equal(calls.save.length,0);assert.equal(calls.revoked.length,0);
  const revoke=calls.timers.find(t=>t.ms===30000);assert.ok(revoke);revoke.fn();assert.deepEqual(calls.revoked,['blob:download-fixture']);
});
test('Tauri resource downloads preserve the bridge path and browser failure creates no download anchor',async()=>{
  const bridge=load({bridgeResponse:{status:200,headers:{'Content-Disposition':'attachment; filename="original.txt"'},bodyBase64:btoa('transcript')}});
  bridge.api.setNativeBridgeEnabled(true);
  assert.equal(await bridge.api.downloadOriginalTranscript('a','txt'),true);
  assert.equal(bridge.calls.bridge[0].name,'engine_api_request');
  assert.equal(bridge.calls.bridge[0].payload.request.path,'/api/v1/videos/a/transcript/export?format=txt');
  assert.equal(bridge.calls.fetch.length,0);assert.equal(bridge.calls.anchors[0].download,'original.txt');
  const failed=load({response:()=>new Response(JSON.stringify({detail:'Transcript not available'}),{status:404})});
  await assert.rejects(failed.api.downloadOriginalTranscript('a','txt'),e=>e.status===404);
  assert.equal(failed.calls.anchors.length,0);
});
