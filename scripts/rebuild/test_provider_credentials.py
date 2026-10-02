"""Main acceptance: real native ASGI/settings SQLite; explicit test credentials only."""
import asyncio,copy,json,os,sys,uuid
from pathlib import Path
WT=Path(__file__).resolve().parents[2]
OUT=WT/'.test-output/provider-bridge';OUT.mkdir(parents=True,exist_ok=True)
PROFILE=OUT/('backend-'+uuid.uuid4().hex);PROFILE.mkdir()
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('API_KEY'):os.environ.pop(k,None)
os.environ.update(RUNTIME_PROFILE='desktop-native',APP_STORAGE_ROOT=str(PROFILE),AIVE_DESKTOP_DATA_ROOT=str(PROFILE),TEMP_PATH=str(PROFILE/'Temp'),CONFIG_PATH=str(PROFILE/'Config'),LOG_PATH=str(PROFILE/'Logs'),DESKTOP_DB_PATH=str(PROFILE/'Config/engine.sqlite3'),DESKTOP_VECTOR_ROOT=str(PROFILE/'VectorStore'),DATABASE_URL='')
sys.path[:0]=[str(WT/'backend'),str(WT/'backend/app')]
from config import settings
from desktop_native.app import create_native_app
from db.database import init_db,dispose_db,async_session
from db.models import AppAISettings
from services import app_settings as svc
from models.schemas import AppSettingsUpdateRequest
from fastapi import HTTPException
import httpx
from types import SimpleNamespace
cases=[]
def passed(name):cases.append({'name':name,'status':'PASS'});print('PASS',name,flush=True)
KEY='EXPLICIT-TEST-SENTINEL-credential-ABCD';OTHER='EXPLICIT-TEST-SENTINEL-second-WXYZ'
paths=SimpleNamespace(exports=PROFILE/'Exports',uploads=PROFILE/'Uploads')
for p in (paths.exports,paths.uploads):p.mkdir()
runtime=SimpleNamespace(paths=paths,bearer_token='explicit-test-session')
def keys():return {k:getattr(settings,f) for k,f in svc.API_KEY_SETTINGS_FIELDS.items()}
async def main():
 await init_db()
 svc.apply_desktop_credentials({'openai':KEY});app=create_native_app(runtime);assert not any(keys().values())
 passed('fresh native app clears prior session credential map')
 auth={'Authorization':'Bearer '+runtime.bearer_token}
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
  for h in ({},{'Authorization':'Bearer wrong'}):
   res=await client.post('/engine-control/credentials',headers=h,json={'openai':KEY});assert res.status_code==401 and not any(keys().values())
  assert (await client.post('/api/v1/engine-control/credentials',headers=auth,json={})).status_code==404
  passed('private credential route requires session bearer; unavailable under public API prefix')
  res=await client.post('/engine-control/credentials',headers=auth,json={'openai':KEY,'mistral':OTHER});assert res.status_code==200 and res.json()=={'status':'applied','configuredProviders':['mistral','openai']};assert KEY not in res.text and OTHER not in res.text
  res=await client.post('/engine-control/credentials',headers=auth,json={'deepseek':OTHER});assert res.status_code==200 and keys()=={'mistral':'','openai':'','deepseek':OTHER,'alibaba':''}
  passed('authenticated snapshots acknowledge names only and replace/clear omitted providers')
  before=keys()
  invalid=[b'[]',b'null',b'{',b'{"unknown":"secret"}',b'{"openai":null}',b'{"openai":1}',b'{"openai":""}',json.dumps({'openai':'x'*8193}).encode(),b'{"openai":"a\\nsecret"}',b'{"openai":"a\\u0080secret"}',b'{"openai":"one","openai":"two"}',b'\xff',b' '*131073]
  for raw in invalid:
   res=await client.post('/engine-control/credentials',headers=auth,content=raw);assert res.status_code==422,(len(raw),res.status_code);assert res.json()=={'detail':'Invalid desktop credentials.'};assert keys()==before
  passed('malformed/duplicate/unknown/control/oversize credentials reject atomically without input echo')
  async with async_session() as db:
   assert await db.get(AppAISettings,'default') is None
   try:await svc.update_ai_settings(db,AppSettingsUpdateRequest(api_keys={'openai':{'api_key':KEY}}))
   except HTTPException as exc:assert exc.status_code==409
   else:raise AssertionError('native API key write accepted')
   assert await db.get(AppAISettings,'default') is None
   record=await svc.get_or_create_ai_settings(db)
   record.api_keys_json={'openai':{'source':'env','env_var':'OPENAI_API_KEY'},'deepseek':{'source':'encrypted_db','encrypted_value':'legacy','last_four':'WXYZ'}}
   os.environ['OPENAI_API_KEY']='INHERITED-ENV-SECRET'
   svc.apply_settings_record(record);assert keys()==before
   response=svc.settings_response(record).model_dump();statuses=response['api_keys'];assert set(statuses)==set(svc.API_KEY_SETTINGS_FIELDS)
   for name,status in statuses.items():assert status['source']=='desktop' and status['env_var'] is None and status['display_value']==('********' if name=='deepseek' else None)
   assert all(v not in json.dumps(response) for v in (KEY,OTHER,'WXYZ','INHERITED-ENV-SECRET'))
   legacy=copy.deepcopy(record.api_keys_json)
   await svc.update_ai_settings(db,AppSettingsUpdateRequest(domain_terms=['lecture-term'],api_keys={}))
   assert keys()==before and record.api_keys_json==legacy;await db.commit()
  passed('native legacy env/DB never override vault map; public settings reveal no suffix; ordinary preference save preserves keys')
  raw=(PROFILE/'Config/engine.sqlite3').read_bytes();assert KEY.encode() not in raw and OTHER.encode() not in raw
  passed('actual settings SQLite contains no bridge credential plaintext')
  await client.post('/engine-control/credentials',headers=auth,json={});assert not any(keys().values())
  passed('empty authenticated snapshot removes all current-session credentials')
 settings.RUNTIME_PROFILE='development';record=AppAISettings(preferred_processing_mode='hybrid',fallback_enabled=True,capabilities_json={},api_keys_json={'openai':{'source':'env','env_var':'OPENAI_API_KEY'}},domain_terms_json=[],local_model_paths_json={})
 svc.apply_settings_record(record);assert settings.OPENAI_API_KEY=='INHERITED-ENV-SECRET';assert svc.settings_response(record).api_keys['openai'].source=='env'
 passed('Docker/non-native environment-backed settings behavior preserved')
 await dispose_db()
 (OUT/'backend-acceptance.json').write_text(json.dumps({'status':'PASS','scope':'Actual source native ASGI route and SQLite; synthetic credentials, no live provider/frozen/installed claim','cases':cases},indent=2))
asyncio.run(main())
