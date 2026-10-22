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
node = sys.argv[2] if len(sys.argv) > 2 else 'node'
ts = str(Path(sys.argv[3]).resolve()) if len(sys.argv) > 3 else str(root/'desktop/node_modules/typescript/lib/typescript.js')
manifest = json.loads((root/'contracts/rebuild/components.json').read_text(encoding='utf-8'))
source = (root/'scripts/rebuild/package_delivery.py').read_text(encoding='utf-8')
tree = ast.parse(source)
functions = {'require','text','integer','safe_name','canonical_origin','validate_vendor_binding','external_component_record','validate_component','public_identity','validate_release','validate_acceptance','reject_private'}
constants = {'REPOSITORY','COMPONENTS','GATES','QUALIFICATIONS','PROBES','VERSION','COMMIT','SHA256'}
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
check(list(rows)==['aive-engine','ffmpeg','documents','whisper-small'],'engine remains first unavailable CI component')
check(rows['aive-engine']['sha256']=='f379e3f0018911258d875520a1e7bf8ed267619693dcf376b151f886133f5136' and rows['aive-engine']['sizeBytes']==254125047,'accepted engine unchanged')
check(rows['whisper-small']['sha256']=='bff80723000e5e058230f8ae27751a4e2ed4378d5dc1c0f849222cb5d022213f' and rows['whisper-small']['sizeBytes']==451226025,'accepted Whisper unchanged')
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
for cid in ['ffmpeg','documents']:
 binding=ns['external_component_record'](rows[cid],release)
 check(binding['distribution']=='vendor-download' and binding['sourceIdentity'] is None and binding['sourceAssociation']['status']=='unverified-vendor-build' and binding['sourceAssociation']['declaredSourceCommit'] is None,'honest vendor binding without fictitious source commit')
 for mutation in [{'url':'http://vendor.example/1.2.3/a.zip'},{'url':'https://vendor.example/latest/a.zip'},{'downloadOrigins':['https://github.com/path']},{'downloadOrigins':['https://user:pass@github.com']},{'downloadOrigins':['https://*.example']},{'downloadOrigins':['https://unlisted.example']},{'downloadOrigins':[]},{'sizeBytes':0},{'sha256':'not-a-hash'},{'distribution':'remote-guess'}]:
  value={**copy.deepcopy(rows[cid]),**mutation}
  rejects(lambda:ns['validate_component'](value),'reject unsafe/unpinned vendor binding '+repr(mutation))
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
check(all(rows[c]['archive'] not in config for c in ['ffmpeg','documents']),'vendor binaries excluded from installer resources')
installer=(root/'desktop/installer/integrated-setup.nsh').read_text(encoding='utf-8')
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
check("expectedManifest.components[0].url,undefined" in smoke and "'aive-engine'" in smoke,'engineering smoke still stops at first no-URL engine')
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
  let calls=0;const sandbox={exports:{},URL,Set,Map,Error,RELEASE:manifest.releaseVersion,app:{isPackaged:patch.packaged??true},process:{argv:patch.args??['app.exe','--aive-complete-setup']},quitting:patch.quitting??false,preparing:patch.preparing??false,restarting:patch.restarting??false,state:{phase:patch.phase??'awaiting_confirmation',error:patch.error??null,setupComplete:patch.setupComplete??false,engineState:patch.engineState??'stopped'},prepare:async()=>{calls++;}};
  vm.runInNewContext(js.outputText,sandbox);sandbox.api.validateManifest(manifest);await sandbox.api.completeInstallerSetup();assert.equal(calls,Object.keys(patch).length===0?1:0);count++;
 }
 assert.ok(main.includes('})).then(()=>completeInstallerSetup())'),'handoff occurs after serialized initialization settles');
 assert.ok(components.includes("c.distribution==='vendor-download'?[]:this.offline"),'vendor rows do not read adjacent offline binaries');
 const tsx=fs.readFileSync(root+'/desktop/src/electron/ElectronSetup.tsx','utf8');assert.equal(ts.createSourceFile('setup.tsx',tsx,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX).parseDiagnostics.length,0);
 console.log(JSON.stringify({status:'PASS',cases:count,targetModuleImported:false,network:false,nativeOrAppExecution:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
result=subprocess.run([node,'-e',node_check,str(root),ts],capture_output=True,text=True,timeout=15)
assert result.returncode==0,result.stderr
node_result=json.loads(result.stdout)
print(json.dumps({'status':'PASS','pythonPureAssertions':checks,'nodeMockResult':node_result,'targetModuleImported':False,'assemblerExecuted':False,'archivesReadOrCreated':False,'network':False,'nativeOrAppExecution':False,'build':False}))
