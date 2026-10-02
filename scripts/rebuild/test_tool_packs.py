"""Main focused tool pack safety checks; synthetic payloads, no functional claims."""
from pathlib import Path
import contextlib,hashlib,io,json,os,struct,sys,tempfile,unittest,zipfile
scripts=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
sys.path.insert(0,str(scripts));import package_tools as tools
class ToolPackSafety(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='tool-pack-fixture-',dir=tools.AUTHORIZED_ROOT);self.root=Path(self.temp.name);self.source=self.root/'documents';self.source.mkdir()
  for file in ('program/soffice.com','program/soffice.exe'):
   path=self.source/file;path.parent.mkdir(parents=True,exist_ok=True);data=bytearray(128);data[:2]=b'MZ';struct.pack_into('<I',data,60,64);data[64:68]=b'PE\0\0';path.write_bytes(data)
  self.module=self.source/'program/python-core-3.12.14/lib/venv';self.module.mkdir(parents=True)
  for name in ('__init__.py','__main__.py'):(self.module/name).write_text('Synthetic module fixture',encoding='utf8')
  (self.source/'NOTICE').write_text('Synthetic original notice',encoding='utf8');(self.source/'Fonts').mkdir();(self.source/'Fonts/example.ttf').write_bytes(b'Synthetic font fixture')
 def tearDown(self):self.temp.cleanup()
 def test_exact_stdlib_files_and_resources_retained(self):
  files,excluded,caches=tools.collect_payload('documents',self.source)
  for name in ('program/python-core-3.12.14/lib/venv/__init__.py','program/python-core-3.12.14/lib/venv/__main__.py','Fonts/example.ttf','NOTICE'):self.assertIn(name,files)
  self.assertEqual(excluded,[]);self.assertEqual(caches,[])
 def test_source_backed_known_cache_recorded_without_deletion(self):
  cache=self.module/'__pycache__/__init__.cpython-312.pyc';cache.parent.mkdir();cache.write_bytes(b'Synthetic generated cache')
  files,excluded,caches=tools.collect_payload('documents',self.source)
  self.assertEqual(caches,['program/python-core-3.12.14/lib/venv/__pycache__/__init__.cpython-312.pyc']);self.assertNotIn(caches[0],files);self.assertTrue(cache.exists())
 def test_all_other_stdlib_descendants_rejected(self):
  for name in ('pyvenv.cfg','arbitrary.py','credentials.json','scripts/activate','__pycache__/arbitrary.cpython-312.pyc'):
   with self.subTest(name=name):
    p=self.module/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('rejected fixture')
    with self.assertRaisesRegex(ValueError,'Unexpected entry'):tools.collect_payload('documents',self.source)
    p.unlink()
    for parent in (p.parent,):
     if parent!=self.module and not list(parent.iterdir()):parent.rmdir()
 def test_hostile_sibling_venv_and_private_paths_rejected(self):
  for name in ('venv','program/venv','program/python-core-3.12.15/lib/venv','profiles','.env'):
   with self.subTest(name=name):
    p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'Private fixture')
    with self.assertRaisesRegex(ValueError,'Private/development'):tools.collect_payload('documents',self.source)
    p.unlink()
 def test_no_default_input_exemption_or_source_escape(self):
  with self.assertRaisesRegex(ValueError,'Private/development'):tools.contained_input(self.module/'__init__.py')
  outside=self.root/'outside.py';outside.write_bytes(b'x')
  with self.assertRaisesRegex(ValueError,'escaped approved source'):tools.contained_input(outside,documents_source_root=self.source)
  self.assertEqual(tools.contained_input(self.module/'__init__.py',documents_source_root=self.source),self.module/'__init__.py')
 def test_package_stream_revalidation_preserves_modules(self):
  notice=self.root/'notice.txt';notice.write_bytes(b'Synthetic notice');metadata=self.root/'source.json';metadata.write_text('{"sourceCommit":"1111111111111111111111111111111111111111"}');inventory=self.root/'inventory.json';inventory.write_text('[{"name":"synthetic","version":"1.0.0"}]')
  previous=sys.argv;sys.argv=['package_tools.py','--component','documents','--version','26.2.6-tdf.3','--release-version','2.1.0-rebuild.2','--source-root',str(self.source),'--notice',str(notice),'--source-metadata',str(metadata),'--dependency-inventory',str(inventory),'--output-dir',str(self.root/'package')]
  try:
   with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(tools.main(),0)
  finally:sys.argv=previous
  descriptor=json.loads((self.root/'package/documents-component.json').read_text());component=descriptor['components'][0];archive=self.root/'package'/component['archive'];self.assertEqual(component['sha256'],hashlib.sha256(archive.read_bytes()).hexdigest())
  with zipfile.ZipFile(archive) as packed:
   for name in ('__init__.py','__main__.py'):self.assertEqual(packed.read('program/python-core-3.12.14/lib/venv/'+name),(self.module/name).read_bytes())
if __name__=='__main__':unittest.main(verbosity=2)
