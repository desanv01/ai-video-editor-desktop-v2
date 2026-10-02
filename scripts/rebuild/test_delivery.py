"""Main-owned synthetic delivery safety checks; no installed acceptance claim."""
from pathlib import Path
import contextlib,copy,hashlib,importlib,json,os,struct,sys,tempfile,unittest,zipfile,io
scripts=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
sys.path.insert(0,str(scripts));import package_delivery as delivery

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value),encoding='utf8')
def zipfiles(path,files):
 with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
  for name,data in sorted(files.items()):archive.writestr(name,data)

class DeliverySafety(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='delivery-fixture-',dir=delivery.AUTHORIZED_ROOT)
  self.root=Path(self.temp.name);self.packs=self.root/'components';self.packs.mkdir();self.version='2.1.0-rebuild.2';self.commit='1'*40
  installer=self.root/'fixture-Setup.exe';data=bytearray(120);data[:2]=b'MZ';struct.pack_into('<I',data,60,64);data[64:68]=b'PE\0\0';installer.write_bytes(data)
  source=self.root/'fixture-source.zip';zipfiles(source,{'README.txt':b'Synthetic source fixture only'})
  self.manifest={'schemaVersion':'aive.components.v1','releaseVersion':self.version,'platform':'win32','architecture':'x64','components':[]}
  for cid in sorted(delivery.COMPONENTS):
   embedded={'component':cid,'version':self.version,'metadata':{('runtimeSourceCommit' if cid=='whisper-small' else 'sourceCommit'):self.commit}}
   members={'bin/tool.exe':b'Synthetic executable fixture','source-identity.json':json.dumps(embedded).encode()}
   if cid=='aive-engine':members['bin/_internal/certifi/cacert.pem']=b'Public CA fixture'
   zipfiles(self.packs/(cid+'.zip'),members)
   self.manifest['components'].append({'id':cid,'version':self.version,'archive':cid+'.zip','sizeBytes':(self.packs/(cid+'.zip')).stat().st_size,'sha256':sha(self.packs/(cid+'.zip')),'expandedBytes':sum(map(len,members.values())),'required':True,'entrypoints':{'tool':'bin/tool.exe'},'probes':[{'kind':'engine-self-test','entrypoint':'tool'}]})
  self.release={'schemaVersion':'aive.delivery-inputs.v1','releaseVersion':self.version,'platform':'win32','architecture':'x64','sourceCommit':self.commit,'githubRepository':delivery.REPOSITORY,'githubReleaseTag':'v'+self.version,'ci':{'runId':1,'runUrl':f'https://github.com/{delivery.REPOSITORY}/actions/runs/1','commit':self.commit,'status':'success'},'qualification':{q:'Synthetic fixture only, not a verified capability' for q in delivery.QUALIFICATIONS},'componentSourceCommits':{c:self.commit for c in delivery.COMPONENTS},'installer':delivery.public_identity(delivery.identity(installer)),'sourceArchive':delivery.public_identity(delivery.identity(source))}
  self.acceptance={'schemaVersion':'aive.delivery-acceptance.v1','releaseVersion':self.version,'sourceCommit':self.commit,'installerSha256':sha(installer),'status':'passed','gates':{g:{'status':'passed','evidence':'Synthetic schema fixture only; no installed execution'} for g in delivery.GATES}}
  self.paths={'installer':installer,'component-manifest':self.root/'manifest.json','source-archive':source,'release-record':self.root/'release.json','acceptance-record':self.root/'acceptance.json','guide':self.root/'guide.txt','notice':self.root/'NOTICE.txt','component-directory':self.packs}
  self.paths['guide'].write_text('Synthetic brief guide',encoding='utf8');self.paths['notice'].write_text('Synthetic notice',encoding='utf8');self.persist()
 def tearDown(self):self.temp.cleanup()
 def persist(self):
  write(self.paths['component-manifest'],self.manifest);write(self.paths['release-record'],self.release);write(self.paths['acceptance-record'],self.acceptance)
 def run_pack(self,name='out'):
  previous=sys.argv;sys.argv=['package_delivery.py']+[item for flag,path in self.paths.items() for item in ('--'+flag,str(path))]+['--output-dir',str(self.root/name)]
  try:
   with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(delivery.main(),0)
  finally:sys.argv=previous
  return self.root/name/f'AIVE-Desktop-{self.version}-win32-x64-delivery.zip'
 def edit_pack(self,cid,mutate):
  path=self.packs/(cid+'.zip')
  with zipfile.ZipFile(path) as archive:members={i.filename:archive.read(i) for i in archive.infolist()}
  mutate(members);zipfiles(path,members)
  row=next(r for r in self.manifest['components'] if r['id']==cid);row.update(sizeBytes=path.stat().st_size,sha256=sha(path),expandedBytes=sum(map(len,members.values())));self.persist()
 def rejected(self,pattern):
  self.persist()
  with self.assertRaisesRegex(ValueError,pattern):self.run_pack()
  self.assertFalse((self.root/'out').exists(),'Rejected prerequisites must not create output')
 def test_deterministic_complete_layout_and_checksums(self):
  first=self.run_pack();second=self.run_pack('out2');self.assertEqual(sha(first),sha(second))
  with zipfile.ZipFile(first) as archive:
   hashes=archive.read('SHA256SUMS.txt').decode().splitlines();self.assertEqual(len(hashes),12)
   for line in hashes:
    digest,name=line.split('  ',1);self.assertEqual(digest,hashlib.sha256(archive.read(name)).hexdigest())
   record=json.loads(archive.read('DELIVERY.json'));self.assertEqual(record['sourceCommit'],self.commit);self.assertEqual(len(record['components']),4)
 def test_every_required_gate_is_enforced(self):
  for gate in sorted(delivery.GATES):
   with self.subTest(gate=gate):
    original=self.acceptance['gates'][gate];self.acceptance['gates'][gate]={'status':'pending','evidence':'not accepted'};self.rejected('Missing/unpassed gate');self.acceptance['gates'][gate]=original
 def test_missing_gate_and_failed_overall(self):
  self.acceptance['gates'].pop('installedExport');self.rejected('exactly all eleven')
 def test_ci_source_and_installer_identity(self):
  for target in ('ci','installer','sourceArchive'):
   with self.subTest(target=target):
    old=copy.deepcopy(self.release[target]);self.release[target]['commit' if target=='ci' else 'sha256']='0'* (40 if target=='ci' else 64);self.rejected('identity|filename/size/hash');self.release[target]=old
 def test_no_overwrite(self):
  path=self.run_pack();digest=sha(path)
  with self.assertRaisesRegex(ValueError,'fresh and absent'):self.run_pack()
  self.assertEqual(digest,sha(path))
 def test_actual_component_hash_checked(self):
  (self.packs/'ffmpeg.zip').write_bytes(b'Corrupt replacement');self.rejected('Actual component size/hash mismatch')
 def test_engine_ca_exception_is_exact_and_scoped(self):
  for cid,name in [('ffmpeg','bin/_internal/certifi/cacert.pem'),('aive-engine','bin/_internal/certifi/CACERT.pem'),('aive-engine','bin/private.pem')]:
   with self.subTest(cid=cid,name=name):
    path=self.packs/(cid+'.zip');original=path.read_bytes();row=copy.deepcopy(next(r for r in self.manifest['components'] if r['id']==cid))
    self.edit_pack(cid,lambda members:members.update({name:b'PEM fixture'}));self.rejected('Private file')
    path.write_bytes(original);self.manifest['components'][next(i for i,r in enumerate(self.manifest['components']) if r['id']==cid)]=row
 def test_source_ca_and_private_data_rejected(self):
  for name in ('bin/_internal/certifi/cacert.pem','.env','credentials.json','db.sqlite3','events.log'):
   with self.subTest(name=name):
    path=self.paths['source-archive'];zipfiles(path,{name:b'private fixture'});self.release['sourceArchive']=delivery.public_identity(delivery.identity(path));self.rejected('Private')
 def test_whisper_declarations_must_all_match(self):
  def mutate(members):
   value=json.loads(members['source-identity.json']);value['sourceCommit']='2'*40;members['source-identity.json']=json.dumps(value).encode()
  self.edit_pack('whisper-small',mutate);self.rejected('source commit absent/unmatched')
 def test_other_component_rejects_runtime_alias(self):
  def mutate(members):
   value=json.loads(members['source-identity.json']);value['metadata']={'runtimeSourceCommit':self.commit};members['source-identity.json']=json.dumps(value).encode()
  self.edit_pack('ffmpeg',mutate);self.rejected('source commit absent/unmatched')
 def test_hostile_zip_paths_and_collisions(self):
  for names in (['../bad'],['Bin/a','bin/b'],['item','item/file'],['NUL.txt'],['file','File']):
   with self.subTest(names=names):
    path=self.root/'hostile.zip';zipfiles(path,{n:b'x' for n in names})
    with self.assertRaises(ValueError):delivery.inspect_zip(path)
 def test_symlink_zip_rejected(self):
  path=self.root/'link.zip'
  with zipfile.ZipFile(path,'w') as archive:
   info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(0o120777<<16);archive.writestr(info,b'target')
  with self.assertRaisesRegex(ValueError,'Nonregular/symlink'):delivery.inspect_zip(path)
 def test_changed_input_during_assembly_is_not_published(self):
  original=delivery.identity;calls=0
  def identity(path):
   nonlocal calls
   calls+=1
   result=original(path)
   if calls==8:self.paths['guide'].write_text('Changed after initial hash',encoding='utf8')
   return result
  delivery.identity=identity
  try:
   with self.assertRaisesRegex(ValueError,'Input changed'):self.run_pack()
   self.assertEqual(list((self.root/'out').glob('*')),[])
  finally:delivery.identity=original
 def test_duplicate_json_fields_rejected(self):
  with self.assertRaisesRegex(ValueError,'Duplicate JSON key'):delivery.parse_json(b'{"sourceCommit":"a","sourceCommit":"b"}','fixture')

if __name__=='__main__':unittest.main(verbosity=2)
