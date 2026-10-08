"""Verify the production same-directory profile alias guard and optional native conversion."""
import argparse, asyncio, ctypes, json, os, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
parser=argparse.ArgumentParser();parser.add_argument('--repo',default='.');parser.add_argument('--output',required=True);parser.add_argument('--libreoffice-root');parser.add_argument('--temp-root');parser.add_argument('--deck');args=parser.parse_args()
repo=Path(args.repo).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
os.environ.update(RUNTIME_PROFILE='desktop-native',APP_STORAGE_ROOT=str(out/'profile'),TEMP_PATH=str(out/'temp'),DESKTOP_DB_PATH=str(out/'profile/Config/engine.sqlite3'),DESKTOP_VECTOR_ROOT=str(out/'profile/VectorStore'))
sys.path.insert(0,str(repo/'backend/app'));from desktop_native import document_conversion as module
from config import settings
records=[];profile=out/'owned-profile';profile.mkdir()
class Function:
 def __init__(self,value=None,result=None):self.value=value;self.result=result
 def __call__(self,source,buffer,size):
  if self.value is not None:buffer.value=self.value
  return self.result if self.result is not None else len(self.value or '')
def fake(value=None,result=None):return patch.object(ctypes,'WinDLL',return_value=SimpleNamespace(GetShortPathNameW=Function(value,result)),create=True)
def test(name,fn):
 try:fn();records.append({'name':name,'status':'passed'})
 except Exception as exc:records.append({'name':name,'status':'failed','error':str(exc)})
 print(records[-1],flush=True)
def check(condition):assert condition
def rejects(value):
 with fake(value):
  try:module._profile_uri(profile)
  except module.ManagedDocumentError:return
  raise AssertionError('Unsafe alias accepted')
def fallback(result):
 with fake(result=result):check(module._profile_uri(profile)==profile.as_uri())
def non_windows():
 with patch.object(module,'os',SimpleNamespace(name='posix')):check(module._profile_uri(profile)==profile.as_uri())
test('non-Windows-keeps-original-uri',non_windows)
if os.name=='nt':
 test('API-failure-falls-back',lambda:fallback(0));test('oversize-API-result-falls-back',lambda:fallback(32768))
 def unchanged():
  with fake(str(profile)):check(module._profile_uri(profile)==profile.as_uri())
 test('no-short-name-keeps-original-uri',unchanged)
 test('relative-alias-rejected',lambda:rejects('relative-profile'))
 other=out/'other-profile';other.mkdir();test('different-directory-alias-rejected',lambda:rejects(str(other)))
 def actual_alias():
  uri=module._profile_uri(profile);check(uri.startswith('file:'));check(profile.is_dir())
 test('real-Windows-alias-api',actual_alias)
if args.libreoffice_root:
 from pptx import Presentation
 settings.LIBREOFFICE_COMPONENT_ROOT=str(Path(args.libreoffice_root).resolve());settings.LIBREOFFICE_BINARY_PATH=str(Path(settings.LIBREOFFICE_COMPONENT_ROOT)/'program/soffice.com')
 settings.TEMP_PATH=str(Path(args.temp_root).resolve());before=set(Path(settings.TEMP_PATH).glob('aive-document-*'));start=time.monotonic()
 def conversion():
  pages=asyncio.run(module.extract_native_pptx_pages(args.deck,str(out/'slides'),dpi=100,presentation_factory=Presentation))
  check(len(pages)==3 and all(not p.get('error') and Path(p['image_path']).is_file() and 'Table retained' in p['text'] and '[Speaker Notes]' in p['text'] for p in pages))
  check(set(Path(settings.TEMP_PATH).glob('aive-document-*'))==before)
  (out/'pages.json').write_text(json.dumps(pages,indent=2),encoding='utf-8')
 test('actual-default-installed-temp-three-pages-and-owned-cleanup',conversion)
 records[-1]['seconds']=round(time.monotonic()-start,3)
receipt={'status':'passed' if records and all(r['status']=='passed' for r in records) else 'failed','scope':'Production profile URI guard; optional actual managed LibreOffice helper uses unchanged installed default TEMP_PATH. No providers or data migration. Short aliases are filesystem-dependent, not guaranteed on ReFS/NTFS.','cases':records};(out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(json.dumps(receipt));sys.exit(receipt['status']!='passed')
