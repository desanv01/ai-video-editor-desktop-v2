"""Focused safety/identity checks for captured application-notice assembly."""
import argparse,copy,hashlib,json,os,shutil,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);root=Path(os.environ.get('AIVE_REBUILD_ROOT',r'C:/Users/Dv/Desktop/ai-video-editor-standalone-release-work/rebuild')).resolve();assert out.is_relative_to(root)
node=shutil.which('node');assert node;script=a.repo.resolve()/'scripts/rebuild/assemble_application_notices.cjs';folder=out/'input';folder.mkdir();(folder/'notices').mkdir()
blob=b'Synthetic notice fixture\\nExact raw UTF-8: \\xc3\\xa9\\n';digest=hashlib.sha256(blob).hexdigest();notice=folder/'notices'/(digest+'.txt');notice.write_bytes(blob)
records=[]
for name in ['owner-a','owner-b','unresolved']:
 package='node_modules/'+name;n=[] if name=='unresolved' else [{'archivePath':package+'/LICENSE','sizeBytes':len(blob),'sha256':digest,'captured':'notices/'+digest+'.txt'}]
 records.append({'name':name,'version':'1.0.0','license':'MIT','packagePath':package,'packageJsonPath':package+'/package.json','packageJsonSha256':'a'*64,'packageJsonSizeBytes':10,'missingCapturedNotices':not n,'notices':n})
inventory={'schema':'aive.application-notices-inventory.v1','inputs':{'asar':{'sizeBytes':20,'sha256':'b'*64}},'packageRecords':3,'capturedNoticeBlobs':1,'inventory':records,'missingCapturedNotices':[{'name':'unresolved','version':'1.0.0','packageJsonPath':'node_modules/unresolved/package.json'}]}
file=folder/'inventory.json'
def write(value):file.write_text(json.dumps(value),encoding='utf-8')
write(inventory);cases=[]
def run(name,expected):
 target=out/name;proc=subprocess.run([node,str(script),'--inventory',str(file),'--output-dir',str(target)],capture_output=True,text=True)
 assert (proc.returncode==0)==expected,proc.stderr
 if not expected:assert not target.exists()
 cases.append({'name':name,'status':'PASS'});return target
one=run('first',True);two=run('second',True)
assert(one/'THIRD_PARTY_APPLICATION_NOTICES.txt').read_bytes()==(two/'THIRD_PARTY_APPLICATION_NOTICES.txt').read_bytes();assert(one/'notice-assembly.json').read_bytes()==(two/'notice-assembly.json').read_bytes()
text=(one/'THIRD_PARTY_APPLICATION_NOTICES.txt').read_bytes();assert text.count(blob)==1
x=json.loads((one/'notice-assembly.json').read_text());assert x['releaseApproved'] is False and x['missingCapturedNotices'][0]['name']=='unresolved' and x['capturedNoticeBlobs']==1
identity=hashlib.sha256(text).hexdigest();assert x['outputs']['thirdPartyApplicationNotices']['sha256']==identity
proc=subprocess.run([node,str(script),'--inventory',str(file),'--output-dir',str(one)],capture_output=True,text=True);assert proc.returncode!=0 and hashlib.sha256((one/'THIRD_PARTY_APPLICATION_NOTICES.txt').read_bytes()).hexdigest()==identity;cases.append({'name':'existing-output-preserved','status':'PASS'})
notice.write_bytes(blob+b'tamper');run('tampered-rejected-before-output',False);notice.write_bytes(blob)
bad=copy.deepcopy(inventory);bad['inventory'][0]['notices'][0]['captured']='../../outside.txt';write(bad);run('escaping-reference-rejected-before-output',False)
bad=copy.deepcopy(inventory);bad['packageRecords']=4;write(bad);run('count-mismatch-rejected-before-output',False);write(inventory)
proc=subprocess.run([node,str(script),'--inventory',str(file),'--output-dir',str(folder/'overlap')],capture_output=True,text=True);assert proc.returncode!=0 and not(folder/'overlap').exists();cases.append({'name':'input-output-overlap-rejected','status':'PASS'})
receipt={'status':'PASS','scope':__doc__,'cases':cases,'exactRawDeduplicatedBlob':True,'deterministicOutputs':True,'unresolvedReleaseApprovalFalse':True};(out/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
