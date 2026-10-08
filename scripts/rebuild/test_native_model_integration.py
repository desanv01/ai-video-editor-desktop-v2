"""Actual native model ASGI/SQLite integration with tiny pinned model and mocked transfer/probe only."""
import argparse,asyncio,hashlib,io,json,os,sys,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
for key in list(os.environ):
 if key.startswith('AIVE_') or key.endswith('_API_KEY') or key in ('DATABASE_URL','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT'):os.environ.pop(key,None)
sys.path[:0]=[str(a.repo/'backend'),str(a.repo/'backend/app')]
from desktop_native.paths import NativeDesktopPaths
paths=NativeDesktopPaths.from_environment(data_root=a.output/'profile');paths.ensure_directories();os.environ.update(paths.settings_environment());os.environ['RUNTIME_PROFILE']='desktop-native'
from config import settings
from desktop_native import model_store as module,model_catalog as catalog,model_manager as manager
component=a.output/'component'
for rel,content in [('bin/whisper-cli.exe',b'Owned runtime fixture'),('models/ggml-small.bin',b'Protected small fixture'),('probes/jfk.wav',b'Public audio fixture')]:
 f=component/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(content)
(component/'.verified.json').write_text(json.dumps({'sha256':module.PACK_SHA256,'version':module.PACK_VERSION}))
settings.WHISPER_CPP_COMPONENT_ROOT=str(component);settings.WHISPER_CPP_BINARY_PATH=str(component/'bin/whisper-cli.exe');settings.WHISPER_CPP_MODEL_PATH=str(component/'models/ggml-small.bin');settings.WHISPER_CPP_MODEL_ID='small';settings.LOCAL_TRANSCRIPTION_MODEL_PATH=settings.WHISPER_CPP_MODEL_PATH
payload=b'0123456789abcdefghijklmn';specs={k:catalog.ModelSpec(k,f'ggml-{k}.bin',len(payload),hashlib.sha256(payload).hexdigest(),f'https://fixture.example/{k}') for k in ('small','medium','large-v3')}
def lookup(k):
 if k not in specs:raise ValueError('Unknown fixture model')
 return specs[k]
class Response:
 status=200;headers={'Content-Length':str(len(payload))}
 def __init__(self):self.body=io.BytesIO(payload)
 def __enter__(self):return self
 def __exit__(self,*exc):return False
 def geturl(self):return 'https://fixture.example/medium'
 def read(self,size):return self.body.read(size)
from db.database import init_db,dispose_db,async_session
from db.models import AppAISettings
from desktop_native.app import create_native_app
from providers import whisper_cpp as provider
from providers.interfaces import TranscriptionRequest
import httpx
cases=[];token='EXPLICIT-MODEL-INTEGRATION-TEST-SESSION'
async def main():
 await init_db();store=manager.get_native_model_store(settings);base='/api/v1/settings/models/local-transcription';app=create_native_app(SimpleNamespace(bearer_token=token,paths=paths));headers={'Authorization':'Bearer '+token}
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=headers) as c:
  async def check(name,fn):
   try:await fn();cases.append({'name':name,'status':'passed'});print('PASS '+name,flush=True)
   except Exception as exc:cases.append({'name':name,'status':'failed','error':str(exc)});print('FAIL '+name+': '+str(exc),flush=True)
  async def boundaries():
   r=await c.get(base,headers={'Authorization':'Bearer wrong'});assert r.status_code==401
   assert (await c.post(base+'/unknown/download',json={})).status_code==404
   assert (await c.post(base+'/small/download',json={})).status_code==409
   assert (await c.delete(base+'/small')).status_code==409
   r=await c.get(base);assert r.status_code==200,r.text;b=r.json();assert b['native'] and b['runtime_configured'];small=b['models'][0];assert small['downloaded'] and small['bundled'] and not small['can_remove'];assert not b['models'][1]['downloaded']
  async def download():
   r=await c.post(base+'/medium/download',json={'make_active':True});assert r.status_code==202,r.text;assert r.json()['model_id']=='medium'
   deadline=time.monotonic()+10
   while time.monotonic()<deadline:
    r=await c.get(base+'/medium/download');assert r.status_code==200,r.text
    if r.json()['status']=='completed':break
    await asyncio.sleep(.01)
   assert r.json()['status']=='completed' and r.json()['progress_percent']==100 and r.json()['active'],r.text
   b=(await c.get(base)).json();assert b['active_model_id']=='medium' and b['models'][1]['downloaded']
   selected=(await c.get('/api/v1/settings/ai')).json();assert selected['local_model_ids']['transcription']=='medium';assert selected['local_model_paths']['transcription']==store.selection()['file_path'];assert settings.WHISPER_CPP_MODEL_PATH==str(component/'models/ggml-small.bin')
  async def settings_guards():
   async with async_session() as db:before=(await db.get(AppAISettings,'default')).local_model_paths_json.copy()
   r=await c.put('/api/v1/settings/ai',json={'local_model_paths':{'transcription':str(a.output/'arbitrary.bin')}});assert r.status_code==409,r.text
   r=await c.put('/api/v1/settings/ai',json={'local_model_ids':{'transcription':'large-v3'}});assert r.status_code==409,r.text
   async with async_session() as db:assert (await db.get(AppAISettings,'default')).local_model_paths_json==before
   r=await c.put('/api/v1/settings/ai',json={'local_model_ids':{'transcription':'medium'},'local_model_paths':{'transcription':store.selection()['file_path']}});assert r.status_code==200,r.text
  async def lease():
   entered=asyncio.Event();release=asyncio.Event();binding=store.selection()
   async def runner(command,output):
    entered.set();await release.wait();return provider.WhisperCppRunResult(stdout=json.dumps({'transcription':[{'timestamps':{'from':'00:00:00.000','to':'00:00:01.000'},'text':'generic lesson'}]}),stderr='')
   owned=provider.WhisperCppTranscriptionProvider(binary_path=binding['runtime_binary'],model_path=binding['file_path'],model_id='medium',work_dir=str(a.output/'owned-transcription'),runner=runner)
   task=asyncio.create_task(owned.transcribe(TranscriptionRequest(audio_path=str(a.output/'generic.wav'),metadata={})))
   try:
    await asyncio.wait_for(entered.wait(),5);assert store._leases.get('medium')==1;assert (await c.delete(base+'/medium')).status_code==409;assert (await c.post(base+'/medium/activate')).status_code==409
    changed=await c.post(base+'/small/activate');assert changed.status_code==200 and changed.json()['model_id']=='small'
   finally:release.set()
   result=await task;assert result.model=='medium' and store._leases.get('medium')==0
   restored=await c.post(base+'/medium/activate');assert restored.status_code==200,restored.text
  async def cancelled_lease():
   entered=asyncio.Event();cleaned=asyncio.Event();binding=store.selection()
   async def runner(command,output):
    entered.set()
    try:await asyncio.Event().wait()
    finally:cleaned.set()
   owned=provider.WhisperCppTranscriptionProvider(binary_path=binding['runtime_binary'],model_path=binding['file_path'],model_id='medium',work_dir=str(a.output/'cancelled-transcription'),runner=runner)
   owner=asyncio.create_task(owned.transcribe(TranscriptionRequest(audio_path=str(a.output/'generic.wav'),metadata={})))
   await asyncio.wait_for(entered.wait(),5);assert store._leases.get('medium')==1;owner.cancel()
   try:await owner
   except asyncio.CancelledError:pass
   else:raise AssertionError('transcription caller cancellation lost')
   assert cleaned.is_set() and store._leases.get('medium')==0
   assert not list((a.output/'cancelled-transcription').glob('whisper_cpp_*.json'))
  async def remove():
   r=await c.delete(base+'/medium');assert r.status_code==200,r.text;assert not store._paths(specs['medium'])[0].exists();assert store.bundled_model.exists();b=(await c.get(base)).json();assert b['active_model_id']=='small' and not b['models'][1]['downloaded'];assert (await c.get('/api/v1/settings/ai')).json()['local_model_ids']['transcription']=='small'
  async def failed_verify():
   file=store._paths(specs['medium'])[0];file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'x'*len(payload));r=await c.post(base+'/medium/activate');assert r.status_code==409,r.text
   r=await c.get(base+'/medium/download');assert r.status_code==200 and r.json()['status']=='failed';assert store.selection()['model_id']=='small' and file.exists();b=(await c.get(base)).json()['models'][1];assert b['verification_required'] and b['can_verify'] and b['can_remove'] and not b['downloaded']
  for name,fn in [('native-private-catalog-and-owned-operation-boundaries',boundaries),('native-download-qualified-selection-and-protected-settings',download),('settings-reject-manual-path-and-unselected-ID-before-mutation',settings_guards),('captured-provider-lease-blocks-removal-and-replacement',lease),('cancelled-transcription-holds-lease-through-owned-cleanup',cancelled_lease),('remove-active-optional-falls-back-with-bundle-preserved',remove),('failed-verification-stays-unready-and-actionable',failed_verify)]:await check(name,fn)
 manager.shutdown_native_model_store();await dispose_db();receipt={'status':'passed' if all(c['status']=='passed' for c in cases) else 'failed','scope':__doc__,'cases':cases};(a.output/'receipt.json').write_text(json.dumps(receipt,indent=2));return receipt['status']=='passed'
with patch.object(module,'lookup',side_effect=lookup),patch.object(module,'pinned_catalog',return_value=tuple(specs.values())),patch.object(catalog,'lookup',side_effect=lookup),patch.object(manager,'lookup',side_effect=lookup),patch.object(manager,'pinned_catalog',return_value=tuple(specs.values())),patch.object(module.NativeModelStore,'_probe',return_value=None),patch.object(module.urllib.request,'build_opener',return_value=SimpleNamespace(open=lambda req,timeout:Response())):
 raise SystemExit(0 if asyncio.run(main()) else 1)

