"""Main: native self-test profile isolation and inherited user-storage preservation."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest
REPO=Path(sys.argv.pop(1)).resolve() if len(sys.argv)>1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[2]
KEYS=('RUNTIME_PROFILE','APP_ENV','APP_DEBUG','DATABASE_URL','AIVE_DESKTOP_DATA_ROOT','APP_STORAGE_ROOT','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT','CONFIG_PATH','TEMP_PATH','MODEL_STORAGE_PATH','LOCAL_MODEL_STORAGE_PATH')
class NativeSelfTestProfile(unittest.TestCase):
 def exercise(self,profile):
  parent=REPO/'.test-output/selftest-profile';parent.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryDirectory(prefix=profile+'-',dir=parent) as directory:
   root=Path(directory).resolve();user=root/'retained-user-profile';(user/'Config').mkdir(parents=True);sentinel=user/'Config/engine.sqlite3';sentinel.write_bytes(b'OWNED_PROFILE_SENTINEL_NO_DATABASE_IO')
   env=os.environ.copy()
   for key in list(env):
    if key.startswith('AIVE_') or key.endswith('_API_KEY') or key in KEYS:env.pop(key,None)
   env.update(APP_ENV='inherited-fixture',APP_DEBUG='false',DATABASE_URL='postgresql+asyncpg://fixture:fixture@127.0.0.1:9999/never-connected',AIVE_DESKTOP_DATA_ROOT=str(user),APP_STORAGE_ROOT=str(user),DESKTOP_DB_PATH=str(sentinel),DESKTOP_VECTOR_ROOT=str(user/'VectorStore'),CONFIG_PATH=str(user/'Config'),TEMP_PATH=str(user/'Temp'),MODEL_STORAGE_PATH=str(user/'Models'),LOCAL_MODEL_STORAGE_PATH=str(user/'Models'))
   if profile=='docker':env['RUNTIME_PROFILE']='docker'
   code='REPO='+repr(str(REPO))+'\nUSER='+repr(str(user))+'\nKEYS='+repr(KEYS)+'\n'+"""import os,sys,json
from pathlib import Path
sys.path[:0]=[REPO+'/backend',REPO+'/backend/app']
before={k:os.environ.get(k) for k in KEYS}
from native_engine import _self_test
assert _self_test()==0
from config import settings
from db.database import engine
assert settings.is_native_desktop,'Self-test advertised native while using inherited Docker profile'
assert engine.dialect.name=='sqlite','Self-test must import native SQLite, not PostgreSQL driver'
assert not any(n=='asyncpg' or n.startswith('asyncpg.') for n in sys.modules),'Native selftest must not load asyncpg'
assert {k:os.environ.get(k) for k in KEYS}==before,'Self-test must restore inherited caller environment'
assert Path(USER+'/Config/engine.sqlite3').read_bytes()==b'OWNED_PROFILE_SENTINEL_NO_DATABASE_IO'
assert set(p.relative_to(USER).as_posix() for p in Path(USER).rglob('*'))=={'Config','Config/engine.sqlite3'},'Self-test touched inherited user profile'
temporary=Path(settings.APP_STORAGE_ROOT);assert temporary.resolve()!=Path(USER).resolve() and not temporary.exists(),'Self-test temporary profile must be cleaned'
print('PASS native self-test profile/dialect/environment/user-preservation/temp-cleanup')
"""
   if profile=='failure':
    code='REPO='+repr(str(REPO))+'\nUSER='+repr(str(user))+'\nKEYS='+repr(KEYS)+'\n'+"""import os,sys
from pathlib import Path
sys.path[:0]=[REPO+'/backend',REPO+'/backend/app']
import native_engine as module
before={k:os.environ.get(k) for k in KEYS};observed=[];original=module.importlib.import_module
def fail(name,*args,**kwargs):
 if name=='fastapi':
  assert os.environ['RUNTIME_PROFILE']=='desktop-native'
  observed.append(Path(os.environ['AIVE_DESKTOP_DATA_ROOT']))
  raise ImportError('Controlled unavailable required dependency')
 return original(name,*args,**kwargs)
module.importlib.import_module=fail
try:
 try:module._self_test()
 except ImportError as e:assert str(e)=='Controlled unavailable required dependency'
 else:raise AssertionError('Required import failure must propagate')
finally:module.importlib.import_module=original
assert {k:os.environ.get(k) for k in KEYS}==before
assert len(observed)==1 and observed[0]!=Path(USER) and not observed[0].exists()
assert Path(USER+'/Config/engine.sqlite3').read_bytes()==b'OWNED_PROFILE_SENTINEL_NO_DATABASE_IO'
assert set(p.relative_to(USER).as_posix() for p in Path(USER).rglob('*'))=={'Config','Config/engine.sqlite3'}
print('PASS required import failure propagation/environment restoration/temp cleanup/user preservation')
"""
   result=subprocess.run([sys.executable,'-B','-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=90)
   self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
 def test_required_import_failure_preserves_environment_and_user_storage(self):self.exercise('failure')
 def test_unset_profile_native_and_isolated(self):self.exercise('unset')
 def test_inherited_docker_profile_native_and_isolated(self):self.exercise('docker')
if __name__=='__main__':unittest.main(verbosity=2)