"""Fast pure integration checks: selected source declarations, no target imports/I/O.
The only subprocess is trusted Node/TypeScript running selected TS functions in VM
with inert app/prepare mocks. No application, installer, archive or network runs.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
def check_registered_install_directory(installer):
 """Exercise the real callback's small control flow with inert NSIS primitives.
 This is source-level coverage, not a compiler or installed Windows proof.
 """
 hook=re.search(r'!macro customPageAfterChangeDir\n(.*?)!macroend',installer,re.S)
 assert hook and '!ifdef allowToChangeInstallationDirectory' in hook[1]
 assert re.search(r'!undef MUI_PAGE_CUSTOMFUNCTION_PRE\s+!define MUI_PAGE_CUSTOMFUNCTION_PRE AiveInstFilesPre',hook[1])
 callback=re.search(r'Function AiveInstFilesPre\n(.*?)FunctionEnd',hook[1],re.S)
 assert callback,'Install Files PRE callback is wired to the registered-path wrapper'
 def run(current,registered,executable_exists):
  values={'$INSTDIR':current,'$0':'caller-register-sentinel'};stack=[];inside=False;enabled=True;calls=[]
  def expand(value):
   value=value.strip('"').replace('${APP_EXECUTABLE_FILENAME}','Aivora.exe')
   for key,item in values.items():value=value.replace(key,item)
   return value
  def condition(text):
   match=re.fullmatch(r'(\$\w+) (==|!=) (\$\w+|"")',text)
   if match:
    equal=values[match[1]]==expand(match[3]);return equal if match[2]=='==' else not equal
   match=re.fullmatch(r'\$\{FileExists\} "(.+)"',text)
   assert match,'Unsupported callback condition: '+text
   return executable_exists and expand(match[1])==current+'\\Aivora.exe'
  for raw in callback[1].splitlines():
   line=raw.strip()
   if not line or line.startswith('#'):continue
   if line.startswith('${If} '):
    assert not inside;inside=True;enabled=condition(line[6:]);continue
   if line.startswith('${AndIf} '):
    assert inside;enabled=enabled and condition(line[9:]);continue
   if line=='${EndIf}':inside=False;enabled=True;continue
   if not enabled:continue
   if line.startswith('Push '):stack.append(values[line[5:]])
   elif line.startswith('Pop '):values[line[4:]]=stack.pop()
   elif line.startswith('ReadRegStr '):
    match=re.fullmatch(r'ReadRegStr (\$\w+) SHELL_CONTEXT "\$\{INSTALL_REGISTRY_KEY\}" InstallLocation',line)
    assert match,'Read the current shell-context install location only';values[match[1]]=registered
   elif line=='Return':assert not stack;return values,calls
   elif line=='Call instFilesPre':
    calls.append('instFilesPre');values['$0']='default-callback-scratch'
    if 'Aivora' not in values['$INSTDIR']:values['$INSTDIR']+='\\Aivora'
   else:raise AssertionError('Unsupported callback instruction: '+line)
  assert not stack and not inside
  return values,calls
 # Existing custom path stays exact; new destination keeps the default sanitizer.
 for current,registered,exists,expected,calls in [
  (r'C:\Private\app',r'C:\Private\app',True,r'C:\Private\app',[]),
  (r'C:\Fresh\chosen',r'C:\Private\app',False,r'C:\Fresh\chosen\Aivora',['instFilesPre']),
  (r'C:\Private\app',r'C:\Private\app',False,r'C:\Private\app\Aivora',['instFilesPre']),
 ]:
  actual,delegated=run(current,registered,exists)
  assert actual['$INSTDIR']==expected and delegated==calls and actual['$0']=='caller-register-sentinel'
 return 3

if '--registered-installer-path-only' in sys.argv:
 cases=check_registered_install_directory((root/'desktop/installer/integrated-setup.nsh').read_text(encoding='utf-8'))
 print(json.dumps({'status':'PASS','sourceCallbackCases':cases,'scope':'registered-path preserve/new-path fallback/register restoration','nativeOrInstallerExecution':False,'targetModuleImported':False}))
 raise SystemExit(0)

node = sys.argv[2] if len(sys.argv) > 2 else 'node'
ts = str(Path(sys.argv[3]).resolve()) if len(sys.argv) > 3 else str(root/'desktop/node_modules/typescript/lib/typescript.js')
if '--msvc-alias-directories-only' in sys.argv:
 # Exercise the selected production composer/parent/guard functions with an
 # in-memory Windows filesystem. No supplier binary, module import or disk I/O.
 focused = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path').win32,crypto=require('node:crypto');
const root=process.argv[1],ts=require(process.argv[2]);
const source=fs.readFileSync(root+'/desktop/electron/msvcSupplier.ts','utf8');
const tree=ts.createSourceFile('msvcSupplier.ts',source,ts.ScriptTarget.Latest,true);assert.equal(tree.parseDiagnostics.length,0);
const wanted=new Set(['need','normal','compositionParent','composeSupplierRuntime','aliases','policy','noUcrt','ENGINE','WHISPER']);
const selected=tree.statements.filter(n=>ts.isFunctionDeclaration(n)&&wanted.has(n.name?.text)||ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>wanted.has(d.name.getText(tree)))).map(n=>n.getText(tree)).join('\n');
const js=ts.transpileModule(selected+'\nglobalThis.api={composeSupplierRuntime,compositionParent};',{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},reportDiagnostics:true});assert.equal(js.diagnostics.length,0);
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const base='C:\\owned\\component',supplier='C:\\owned\\supplier',packageHash='supplier-package';
const runtimeNames=['MSVCP140.dll','VCRUNTIME140.dll','VCRUNTIME140_1.dll','MSVCP140_ATOMIC_WAIT.dll','VCOMP140.dll'];
async function scenario(unsafe) {
 const nodes=new Map(),copies=[],created=[];
 const key=p=>path.resolve(p).toLowerCase();
 const dir=p=>nodes.set(key(p),{kind:'dir'});
 for(const p of ['C:\\','C:\\owned',base,path.join(base,'_internal'),supplier,path.join(supplier,'runtime')])dir(p);
 const data=new Map(runtimeNames.map(n=>[n,Buffer.from('verified-fixture-'+n)]));
 for(const [name,b] of data)nodes.set(key(path.join(supplier,'runtime',name)),{kind:'file',data:b});
 nodes.set(key(path.join(base,'.msvc-supplier-required.json')),{kind:'file',data:Buffer.from(JSON.stringify({schema:'aive.external-msvc.v1',component:'aive-engine',minimumWindowsMajor:10,packageSha256:packageHash}))});
 const arrow=path.join(base,'_internal','pyarrow.libs');
 if(unsafe==='file')nodes.set(key(arrow),{kind:'file',data:Buffer.from('occupied-parent')});
 if(unsafe==='junction')nodes.set(key(arrow),{kind:'link',target:'C:\\outside'});
 if(unsafe==='realpath')nodes.set(key(arrow),{kind:'dir',target:'C:\\outside'});
 const error=(code)=>Object.assign(new Error(code),{code});
 const get=p=>{const n=nodes.get(key(p));if(!n)throw error('ENOENT');return n;};
 const mock={
  lstat:async p=>{const n=get(p);return {isSymbolicLink:()=>n.kind==='link',isDirectory:()=>n.kind==='dir',isFile:()=>n.kind==='file',nlink:1};},
  realpath:async p=>get(p).target??path.resolve(p),
  mkdir:async p=>{assert.equal(get(path.dirname(p)).kind,'dir');if(nodes.has(key(p)))throw error('EEXIST');dir(p);created.push(path.resolve(p));},
  readdir:async p=>{get(p);return [...nodes.keys()].filter(n=>key(path.dirname(n))===key(p)).map(n=>path.basename(n));},
  readFile:async(p,encoding)=>{const n=get(p);assert.equal(n.kind,'file');return encoding?n.data.toString(encoding):n.data;},
  copyFile:async(from,to,flags)=>{assert.equal(flags,1,'COPYFILE_EXCL retained');assert.equal(get(path.dirname(to)).kind,'dir');if(nodes.has(key(to)))throw error('EEXIST');nodes.set(key(to),{kind:'file',data:Buffer.from(get(from).data)});copies.push({from,to});},
  writeFile:async(p,value,options)=>{assert.equal(options.flag,'wx');assert.ok(!nodes.has(key(p)));nodes.set(key(p),{kind:'file',data:Buffer.from(value)});}
 };
 const files=[...data].map(([name,b])=>({name,bytes:b.length,sha256:hash(b)}));
 const sandbox={exports:{},fs:mock,path,constants:{COPYFILE_EXCL:1},binding:()=>({files}),digest:hash,supported:()=>{},verifyPreparedMsvc:async()=>true,msvcSupplierSignature:()=> 'fixture-binding',MSVC_PACKAGE_SHA256:packageHash};
 vm.runInNewContext(js.outputText,sandbox);
 const signal={throwIfAborted(){}};
 if(unsafe){await assert.rejects(()=>sandbox.api.composeSupplierRuntime('aive-engine',base,supplier,signal),/MSVC_PATH_TYPE|MSVC_PATH_LINK/);assert.equal(copies.length,4);assert.ok(!nodes.has(key(path.join(base,'.msvc-composition.json'))));assert.equal(get(arrow).kind,unsafe==='file'?'file':unsafe==='junction'?'link':'dir');return;}
 assert.ok(!nodes.has(key(arrow)),'Regression precondition: pyarrow.libs entirely absent');
 await sandbox.api.composeSupplierRuntime('aive-engine',base,supplier,signal);
 assert.equal(copies.length,6);assert.equal(get(arrow).kind,'dir');assert.ok(created.includes(arrow));
 const expected=[['MSVCP140.dll','_internal/MSVCP140.dll'],['VCRUNTIME140.dll','_internal/VCRUNTIME140.dll'],['VCRUNTIME140_1.dll','_internal/VCRUNTIME140_1.dll'],['MSVCP140.dll','_internal/numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll'],['MSVCP140.dll','_internal/pyarrow.libs/msvcp140-6e7bcb4ffac2ac140bf7bcc6de529ee1.dll'],['MSVCP140_ATOMIC_WAIT.dll','_internal/pyarrow.libs/msvcp140_atomic_wait-4325193497a3e8a7f3eeff01c806f206.dll']];
 for(const [name,relative] of expected)assert.equal(hash(get(path.join(base,...relative.split('/'))).data),hash(data.get(name)));
 const marker=JSON.parse(get(path.join(base,'.msvc-composition.json')).data.toString());assert.equal(marker.schema,'aive.msvc-composition.v1');assert.equal(marker.component,'aive-engine');assert.equal(marker.bindingSha256,'fixture-binding');
 await assert.rejects(()=>sandbox.api.compositionParent(base,'C:\\outside',signal),/MSVC_COMPOSITION_PARENT_ESCAPE/);
 await assert.rejects(()=>sandbox.api.composeSupplierRuntime('aive-engine',base,supplier,signal),/EEXIST/,'Occupied alias is never overwritten');
}
(async()=>{for(const unsafe of [null,'file','junction','realpath'])await scenario(unsafe);console.log(JSON.stringify({status:'PASS',cases:4,absentAliasParentCreated:true,allSixAliasHashesVerified:true,occupiedParentAndLinkRejected:true,exclusiveCopiesRetained:true,filesystem:'in-memory Windows model',targetModuleImported:false,build:false,network:false,supplierOrEngineExecution:false}));})().catch(e=>{console.error(e);process.exitCode=1;});
"""
 result=subprocess.run([node,'-e',focused,str(root),ts],capture_output=True,text=True,timeout=15)
 assert result.returncode==0,result.stderr
 print(result.stdout.strip())
 raise SystemExit(0)

manifest = json.loads((root/'contracts/rebuild/components.json').read_text(encoding='utf-8'))
source = (root/'scripts/rebuild/package_delivery.py').read_text(encoding='utf-8')
tree = ast.parse(source)
functions = {'require','text','integer','safe_name','canonical_origin','validate_vendor_binding','external_component_record','validate_component','validate_runtime_policy','public_identity','validate_release','validate_acceptance','reject_private'}
constants = {'REPOSITORY','COMPONENTS','GATES','QUALIFICATIONS','PROBES','VERSION','COMMIT','SHA256','MSVC_SUPPLIER'}
selected = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in functions or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
ns = {'re':re,'urlsplit':urlsplit}
exec(compile(ast.Module(body=selected,type_ignores=[]),'selected-pure-delivery-declarations','exec'),ns)
checks = 0

def check(condition, message):
 global checks
 assert condition, message
 checks += 1

def rejects(action, message):
 global checks
 try: action()
 except (ValueError,TypeError): checks += 1
 else: raise AssertionError(message)

rows = {r['id']:r for r in manifest['components']}
check(list(rows)==['msvc-runtime','aive-engine','ffmpeg','documents','whisper-small'],'supplier precedes consumers in five-row manifest')
for cid in ['aive-engine','whisper-small']:
 check(ns['SHA256'].fullmatch(rows[cid]['sha256']) is not None and ns['integer'](rows[cid]['sizeBytes']) and rows[cid].get('requiresMsvcSupplier') is True,'consumer actual future descriptor pins and required external policy '+cid)
check(rows['msvc-runtime']==ns['MSVC_SUPPLIER'],'exact official supplier row')
check(all('url' not in rows[k] for k in ['aive-engine','whisper-small']),'no unexpected bundled URL')
check(rows['ffmpeg']['sha256']=='49b28c5f16addd40239a66949973458769b7056fb7752c30ac0d53389d09a552' and rows['ffmpeg']['sizeBytes']==252194496 and rows['ffmpeg']['archiveRoot']=='ffmpeg-8.1.1-full_build' and rows['ffmpeg']['expandedBytes']==695132454,'original FFmpeg input pins')
check(rows['documents']['sha256']=='f9877032fd908beb9c0ddf06df4af5c2e85f419c42e14876c4cce5aae5fb2660' and rows['documents']['sizeBytes']==373252096 and rows['documents']['archiveFormat']=='msi-admin' and rows['documents']['expandedBytes']==1613546210,'original MSI input pins')
for row in rows.values(): ns['validate_component'](row)
check(True,'all actual manifest rows validate in mixed assembler')
release = {'componentSourceCommits':{'aive-engine':'1'*40,'whisper-small':'2'*40}}
installer={'fileName':'Aivora-Setup.exe','sizeBytes':120,'sha256':'a'*64}
source_archive={'fileName':'source.zip','sizeBytes':120,'sha256':'b'*64}
release_input={'schemaVersion':'aive.delivery-inputs.v1','releaseVersion':'1.2.3','platform':'win32','architecture':'x64','sourceCommit':'1'*40,'githubRepository':ns['REPOSITORY'],'githubReleaseTag':'v1.2.3','ci':{'runId':1,'runUrl':f"https://github.com/{ns['REPOSITORY']}/actions/runs/1",'commit':'1'*40,'status':'success'},'qualification':{q:'explicit unverified mock limitation' for q in ns['QUALIFICATIONS']},'componentSourceCommits':release['componentSourceCommits'],'installer':installer,'sourceArchive':source_archive}
ns['validate_release'](release_input,installer,source_archive)
check(True,'mixed release requires actual bundled source references, not invented vendor commits')
for field in ['installer','sourceArchive','ci']:
 bad=copy.deepcopy(release_input)
 bad[field]['status' if field=='ci' else 'sha256']='failed' if field=='ci' else '0'*64
 rejects(lambda:ns['validate_release'](bad,installer,source_archive),'mixed delivery preserves exact CI/installer/source identity '+field)
for cid in ['aive-engine','whisper-small']:
 bad=copy.deepcopy(release_input);bad['componentSourceCommits'].pop(cid)
 rejects(lambda:ns['validate_release'](bad,installer,source_archive),'mixed delivery cannot waive bundled source commit '+cid)
for cid in ['ffmpeg','documents','msvc-runtime']:
 binding=ns['external_component_record'](rows[cid],release)
 check(binding['distribution']=='vendor-download' and binding['sourceIdentity'] is None and binding['sourceAssociation']['status']=='unverified-vendor-build' and binding['sourceAssociation']['declaredSourceCommit'] is None,'honest vendor binding without fictitious source commit')
 for mutation in [{'url':'http://vendor.example/1.2.3/a.zip'},{'url':'https://vendor.example/latest/a.zip'},{'downloadOrigins':['https://github.com/path']},{'downloadOrigins':['https://user:pass@github.com']},{'downloadOrigins':['https://*.example']},{'downloadOrigins':['https://unlisted.example']},{'downloadOrigins':[]},{'sizeBytes':0},{'sha256':'not-a-hash'},{'distribution':'remote-guess'}]:
  value={**copy.deepcopy(rows[cid]),**mutation}
  rejects(lambda:ns['validate_component'](value),'reject unsafe/unpinned vendor binding '+repr(mutation))
for cid in ['aive-engine','whisper-small']:
 policy={'schema':'aive.external-msvc.v1','component':cid,'minimumWindowsMajor':10,'packageSha256':rows['msvc-runtime']['sha256']}
 ns['validate_runtime_policy'](rows[cid],policy)
 check(True,'consumer policy binds pinned supplier '+cid)
 rejects(lambda:ns['validate_component']({k:v for k,v in rows[cid].items() if k!='requiresMsvcSupplier'}),'consumer cannot omit supplier dependency')
 rejects(lambda:ns['validate_runtime_policy'](rows[cid],{**policy,'packageSha256':'0'*64}),'policy cannot substitute supplier input')
rejects(lambda:ns['validate_component']({**rows['aive-engine'],'distribution':'vendor-download','url':rows['ffmpeg']['url'],'downloadOrigins':rows['ffmpeg']['downloadOrigins']}),'bundled engine cannot claim vendor exclusion')
main = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
loop = next(n for n in main.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='component')
branch = next(n for n in loop.body if isinstance(n,ast.If) and 'vendor-download' in ast.unparse(n.test))
check(any(isinstance(n,ast.Continue) for n in branch.body),'vendor branch bypasses binary read path')
check(not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'input_path','identity','inspect_zip'} for n in ast.walk(branch)),'no vendor binary read/hash/inspect in exclusion branch')
check('Exact source commit required for bundled component' in ast.unparse(loop),'bundled source commit guard remains')
check('source-identity.json' in ast.unparse(loop) and 'Embedded component identity mismatch' in ast.unparse(loop),'bundled actual embedded identity checks remain')
check(len(ns['GATES'])==11,'all eleven delivery gates retained')
accept={'schemaVersion':'aive.delivery-acceptance.v1','releaseVersion':'1.2.3','sourceCommit':'1'*40,'installerSha256':'a'*64,'status':'passed','gates':{g:{'status':'passed','evidence':'mock evidence'} for g in ns['GATES']}}
for gate in ns['GATES']:
 bad=copy.deepcopy(accept);bad['gates'][gate]['status']='pending'
 rejects(lambda:ns['validate_acceptance'](bad,{'releaseVersion':'1.2.3','sourceCommit':'1'*40},{'sha256':'a'*64}),'cannot omit installed acceptance '+gate)
for name in ['credentials.json','.env','db.sqlite3','events.log','private.key']:
 rejects(lambda:ns['reject_private']([name]),'privacy boundary '+name)
config=(root/'desktop/electron-builder.yml').read_text(encoding='utf-8')
check('offline-components/**' not in config and all('offline-components/'+rows[c]['archive'] in config for c in ['aive-engine','whisper-small']),'resource whitelist bundles only exact engine/Whisper archives')
check(all(rows[c]['archive'] not in config for c in ['ffmpeg','documents','msvc-runtime']),'all three supplier binaries excluded from installer resources')
installer=(root/'desktop/installer/integrated-setup.nsh').read_text(encoding='utf-8')
checks += check_registered_install_directory(installer)
direct_launch = 'Exec \'"$INSTDIR\\${APP_EXECUTABLE_FILENAME}" $1\''
check(direct_launch in installer and '--updated --aive-complete-setup' in installer,'interactive direct launch preserves exact executable and update/setup flags')
check('${If} ${UAC_IsAdmin}' in installer and installer.index('${If} ${UAC_IsAdmin}') < installer.index(direct_launch),'elevated current installer guard precedes every direct launch')
elevation_guard=installer.split('Function AiveContinueSetup',1)[1].split('StrCpy $1',1)[0]
check('MessageBox MB_OK|MB_ICONSTOP' in elevation_guard and 'Return' in elevation_guard,'elevated finish is rejected visibly rather than brokered')
check('ClearErrors\n      '+direct_launch in installer and '${If} ${Errors}\n        MessageBox MB_OK|MB_ICONSTOP' in installer,'direct launch error is cleared then handled visibly')
check('StdUtils.ExecShellAsUser' not in installer and 'ExecShell' not in installer,'no COM/shell association fallback in finish handoff')
check('!macro customFinishPage' in installer and '!define MUI_FINISHPAGE_RUN_TEXT "Continue Aivora setup (downloads tools)"' in installer and 'doStartApp' not in installer,'finish checkbox only; default silent macro unchanged')
ui=(root/'desktop/src/electron/ElectronSetup.tsx').read_text(encoding='utf-8')
check('internet connection' in ui and 'directly from their suppliers' in ui and 'reuses verified files' in ui,'connectivity/source/cache copy present')
smoke=(root/'scripts/rebuild/phase2-electron-smoke.cjs').read_text(encoding='utf-8')
check("'msvc-runtime'" in smoke and "'aive-engine'" in smoke and "vendor-download" in smoke and ".url,undefined" in smoke,'engineering smoke retains the no-URL engine boundary with five-row supplier alignment')
ast.parse((root/'scripts/rebuild/test_delivery.py').read_text(encoding='utf-8'))
node_check = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.argv[1],ts=require(process.argv[2]);
const components=fs.readFileSync(root+'/desktop/electron/components.ts','utf8');
const main=fs.readFileSync(root+'/desktop/electron/main.ts','utf8');
function pick(s,names){const t=ts.createSourceFile('source.ts',s,ts.ScriptTarget.Latest,true);assert.equal(t.parseDiagnostics.length,0);return t.statements.filter(n=>ts.isFunctionDeclaration(n)&&names.includes(n.name?.text)||ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>names.includes(d.name.getText(t)))).map(n=>n.getText(t)).join('\n');}
const util=fs.readFileSync(root+'/desktop/electron/util.ts','utf8');
const js=ts.transpileModule(pick(util,['relative'])+'\n'+pick(components,['kinds','validateManifest','validateDownloadOrigins','archivePath'])+'\n'+pick(main,['completeInstallerSetup'])+'\nglobalThis.api={validateManifest,completeInstallerSetup};',{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS},reportDiagnostics:true});assert.equal(js.diagnostics.length,0);
const manifest=JSON.parse(fs.readFileSync(root+'/contracts/rebuild/components.json','utf8'));let count=0;
(async()=>{
 for(const patch of [{},{packaged:false},{args:[]},{quitting:true},{preparing:true},{restarting:true},{phase:'error'},{phase:'cancelled'},{phase:'extracting'},{error:{code:'PREPARATION_INTERRUPTED'}},{error:{code:'MSI_NATIVE_SETTLEMENT_AMBIGUOUS_STAGING_RETAINED'}},{setupComplete:true},{engineState:'ready'}]){
  let calls=0;const sandbox={exports:{},URL,Set,Map,Error,MSVC_PACKAGE_SHA256:manifest.components.find(c=>c.id==='msvc-runtime').sha256,RELEASE:manifest.releaseVersion,app:{isPackaged:patch.packaged??true},process:{argv:patch.args??['app.exe','--aive-complete-setup']},quitting:patch.quitting??false,preparing:patch.preparing??false,restarting:patch.restarting??false,state:{phase:patch.phase??'awaiting_confirmation',error:patch.error??null,setupComplete:patch.setupComplete??false,engineState:patch.engineState??'stopped'},prepare:async()=>{calls++;}};
  vm.runInNewContext(js.outputText,sandbox);sandbox.api.validateManifest(manifest);await sandbox.api.completeInstallerSetup();assert.equal(calls,Object.keys(patch).length===0?1:0);count++;
 }
 assert.ok(main.includes('})).then(()=>completeInstallerSetup())'),'handoff occurs after serialized initialization settles');
 assert.ok(components.includes("c.distribution==='vendor-download'?[]:this.offline"),'vendor rows do not read adjacent offline binaries');
 assert.ok(components.includes('msvcSupplierConfigured()')&&components.includes("c.requiresMsvcSupplier"),'provider configuration and dependent consumers declared');
 const composeAt=components.indexOf('await composeSupplierRuntime(c.id,this.compositionRoot(c,target),supplierRoot,signal)'),probeAt=components.indexOf("await update('probing',c)");assert.ok(composeAt>=0&&probeAt>composeAt,'supplier composition precedes existing consumer probes');
 assert.ok(components.includes('verifyMsvcComposition(c.id,this.compositionRoot(c,root),this.root(supplier))'),'installed consumer composition verified');
 const tsx=fs.readFileSync(root+'/desktop/src/electron/ElectronSetup.tsx','utf8');assert.equal(ts.createSourceFile('setup.tsx',tsx,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX).parseDiagnostics.length,0);
 console.log(JSON.stringify({status:'PASS',cases:count,targetModuleImported:false,network:false,nativeOrAppExecution:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
result=subprocess.run([node,'-e',node_check,str(root),ts],capture_output=True,text=True,timeout=15)
assert result.returncode==0,result.stderr
node_result=json.loads(result.stdout)
print(json.dumps({'status':'PASS','pythonPureAssertions':checks,'nodeMockResult':node_result,'targetModuleImported':False,'assemblerExecuted':False,'archivesReadOrCreated':False,'network':False,'nativeOrAppExecution':False,'build':False}))
