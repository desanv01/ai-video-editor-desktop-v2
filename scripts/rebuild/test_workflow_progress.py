"""Real native API/SQLite regressions for durable manual workflow review progress.
No providers, installed profile writes, rendering or automatic approval.
"""
import argparse, asyncio, json, os, sys, uuid
from pathlib import Path
from types import SimpleNamespace
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('_API_KEY') or k in ('DATABASE_URL','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT'):os.environ.pop(k,None)
sys.path[:0]=[str(a.repo/'backend'),str(a.repo/'backend/app')]
from desktop_native.paths import NativeDesktopPaths
paths=NativeDesktopPaths.from_environment(data_root=a.output/'profile');paths.ensure_directories();os.environ.update(paths.settings_environment());os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['EMBEDDING_DIMENSIONS']='3'
from db.database import init_db,dispose_db,async_session
from db.models import Video,VideoStatus,EditPlan
from desktop_native.app import create_native_app
import httpx
cases=[];token='EXPLICIT-PROGRESS-TEST-ONLY-SESSION-123456789';vid=str(uuid.uuid4());url=f'/api/v1/videos/{vid}/plan';save=url+'/workflow-progress'
def client():return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_native_app(SimpleNamespace(bearer_token=token,paths=paths)),raise_app_exceptions=False),base_url='http://test',headers={'Authorization':'Bearer '+token})
async def exercise():
 await init_db()
 async with async_session() as db:
  db.add(Video(id=uuid.UUID(vid),filename='owned.mp4',original_filename='Owned workflow test',file_path=str(paths.uploads/'owned.mp4'),duration_seconds=6,status=VideoStatus.AWAITING_REVIEW));await db.flush()
  db.add(EditPlan(video_id=uuid.UUID(vid),original_duration=6,estimated_duration=6,is_approved=False,teacher_notes='Retain teacher note',plan_json={'metadata':{'sentinel':{'retained':True}},'sections':[{'id':'section-retained'}],'chapters':[{'label':'Owned chapter','timestamp':0}],'edit_decisions':[],'export_metadata':{'sentinel':'export-retained'}}));await db.commit()
 async def test(name,fn):
  try:await fn();cases.append({'name':name,'status':'PASS'});print('PASS '+name,flush=True)
  except Exception as e:cases.append({'name':name,'status':'FAIL','errorType':type(e).__name__,'detail':str(e)[:400]});print('FAIL '+name+': '+type(e).__name__,flush=True)
 async def durable():
  async with client() as c:
   r=await c.put(save,json={'completed_step':'sections'});assert r.status_code==200, f'Completion must save successfully: {r.status_code}'
   b=r.json();assert b['metadata']['workflow_progress']['completed_steps']==['sections'];assert b['metadata']['sentinel']=={'retained':True};assert b['sections'][0]['id']=='section-retained';assert b['teacher_notes']=='Retain teacher note';assert not b['is_approved']
  await dispose_db()
  async with client() as c:
   r=await c.get(url);assert r.status_code==200;assert r.json()['metadata']['workflow_progress']['completed_steps']==['sections']
   v=await c.get(f'/api/v1/videos/{vid}');assert v.json()['status']=='awaiting_review';assert not v.json()['edit_plan']['is_approved']
 async def ordered():
  async with client() as c:
   for step in ['polish','sections','clean','layout','clean']:
    r=await c.put(save,json={'completed_step':step});assert r.status_code==200
   b=r.json();assert b['metadata']['workflow_progress']['completed_steps']==['clean','sections','layout','polish'];assert not b['is_approved']
 async def normalized():
  async with client() as c:
   before=(await c.get(url)).json();r=await c.put(url+'/captions',json={'enabled':True});assert r.status_code==200
   after=(await c.get(url)).json();assert after['metadata']['workflow_progress']==before['metadata']['workflow_progress'];assert after['metadata']['sentinel']==before['metadata']['sentinel'];assert after['export_metadata']['sentinel']=='export-retained';assert not after['is_approved']
 async def rejected():
  async with client() as c:
   before=(await c.get(url)).json()['metadata']['workflow_progress'];assert (await c.put(save,json={'completed_step':'invented'})).status_code==422
   assert (await c.get(url)).json()['metadata']['workflow_progress']==before
   assert (await c.put(f'/api/v1/videos/{uuid.uuid4()}/plan/workflow-progress',json={'completed_step':'sections'})).status_code==404
   c.headers.pop('Authorization');assert (await c.put(save,json={'completed_step':'export'})).status_code==401
 for name,fn in [('manual-completion-survives-dispose-and-fresh-client-without-approval',durable),('canonical-ordered-idempotent-union',ordered),('subsequent-caption-normalization-preserves-progress-and-unrelated-payload',normalized),('invalid-missing-and-unauthorized-requests-cannot-mutate',rejected)]:await test(name,fn)
 await dispose_db();receipt={'status':'PASS' if all(c['status']=='PASS' for c in cases) else 'FAIL','scope':__doc__.strip(),'cases':cases};(a.output/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');return receipt['status']=='PASS'
raise SystemExit(0 if asyncio.run(exercise()) else 1)
