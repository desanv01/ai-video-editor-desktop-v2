"""Main-owned regressions for three actual installed boundary failures.
Real native ASGI/SQLite/staging and real SDK requests with in-memory transport;
no provider network, user credentials, frozen or installed success inferred.
"""
import argparse, asyncio, hashlib, json, os, sys, uuid
from pathlib import Path
from types import SimpleNamespace

parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();repo=args.repo.resolve();output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
for key in list(os.environ):
 if key.startswith('AIVE_') or key.endswith('_API_KEY') or key in ('DATABASE_URL','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT'):os.environ.pop(key,None)
sys.path[:0]=[str(repo/'backend'),str(repo/'backend/app')]
from desktop_native.paths import NativeDesktopPaths
paths=NativeDesktopPaths.from_environment(data_root=output/'profile');paths.ensure_directories();os.environ.update(paths.settings_environment());os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['EMBEDDING_DIMENSIONS']='3'
from config import settings
from db.database import init_db,dispose_db,async_session
from db.models import Video,VideoStatus,EditPlan
from desktop_native.app import create_native_app
from services.transcription import TranscriptionService
from openai import AsyncOpenAI
import httpx

cases=[]
async def exercise():
 await init_db();app=create_native_app(SimpleNamespace(bearer_token='EXPLICIT-TEST-SESSION-TOKEN-ONLY-123456789',paths=paths))
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test',headers={'Authorization':'Bearer EXPLICIT-TEST-SESSION-TOKEN-ONLY-123456789'}) as client:
  async def create_project(title):
   response=await client.post('/api/v1/projects',json={'title':title});assert response.status_code==200;return response.json()['id']
  async def chunks():
   pid=await create_project('Actual chunk contract');payload=b'owned staged media bytes';init=await client.post(f'/api/v1/projects/{pid}/imports/browser/primary/init',json={'original_filename':'fixture.mp4','file_size_bytes':len(payload),'mime_type':'video/mp4'});assert init.status_code==200
   token=init.json()['token'];url=f'/api/v1/projects/{pid}/imports/browser/primary/{token}'
   for offset,data,phase,complete in [(0,payload[:5],'copying',False),(5,payload[5:],'staged',True)]:
    response=await client.put(url+f'/chunk?offset={offset}',content=data,headers={'Content-Type':'application/octet-stream'});assert response.status_code==200,f'Chunk response must succeed after durable write: {response.status_code}'
    body=response.json();assert body['phase']==phase;assert body['next_offset']==offset+len(data);assert body['bytes_received']==body['next_offset'];assert body['complete'] is complete;assert body['events'][-1]['phase']==phase;assert body['error'] is None
    status=await client.get(url);assert status.status_code==200;assert status.json()=={k:v for k,v in body.items() if k!='next_offset'}
   staged=paths.uploads/init.json()['staging_relative_path'];assert staged.read_bytes()==payload
   conflict=await client.put(url+'/chunk?offset=0',content=payload[:5]);assert conflict.status_code==409
  async def readiness():
   pid=await create_project('Loaded edit plan boundary');source=paths.uploads/'readiness-fixture.mp4';source.write_bytes(b'owned media fixture')
   video_id=uuid.uuid4()
   async with async_session() as db:
    db.add(Video(id=video_id,project_id=uuid.UUID(pid),filename=source.name,original_filename=source.name,file_path=str(source),duration_seconds=10,status=VideoStatus.UPLOADED));await db.commit()
   response=await client.get(f'/api/v1/projects/{pid}/readiness');assert response.status_code==200,f'Fresh uploaded video preflight must not trigger lazy ORM I/O: {response.status_code}';assert response.json()['project_id']==pid
   async with async_session() as db:
    db.add(EditPlan(video_id=video_id,plan_json={'segments':[]},is_approved=True));await db.commit()
   response=await client.get(f'/api/v1/projects/{pid}/readiness');assert response.status_code==200,'Preflight must eagerly load an existing plan too'
  async def credentials():
   service=TranscriptionService();headers=[]
   async def mock(request):
    headers.append((request.url.host,request.headers.get('Authorization')))
    return httpx.Response(200,json={'text':'Bridge design pattern','language':'en','duration':1.0,'words':[],'segments':[]})
   initial_openai,initial_mistral=service._openai,service._mistral
   assert not initial_openai.api_key and not initial_mistral.api_key,'Fixture must begin before credentials are synchronized'
   openai_http=httpx.AsyncClient(transport=httpx.MockTransport(mock));mistral_http=httpx.AsyncClient(transport=httpx.MockTransport(mock))
   service._openai=AsyncOpenAI(api_key=initial_openai.api_key,http_client=openai_http);service._mistral=AsyncOpenAI(api_key=initial_mistral.api_key,base_url=settings.MISTRAL_BASE_URL,http_client=mistral_http)
   audio=paths.temp/'fixture.wav';audio.write_bytes(b'RIFF-owned-audio-fixture')
   try:
    for revision in ('ONE','TWO'):
     snapshot={'openai':'EXPLICIT-TEST-OPENAI-'+revision,'mistral':'EXPLICIT-TEST-MISTRAL-'+revision}
     synced=await client.post('/engine-control/credentials',json=snapshot);assert synced.status_code==200
     before=len(headers);assert (await service._whisper_single(str(audio)))['text'];assert (await service._voxtral_single(str(audio),None,None))['text']
     assert headers[before:]==[('api.openai.com','Bearer '+snapshot['openai']),('api.mistral.ai','Bearer '+snapshot['mistral'])],'SDK requests must use current securely synchronized credentials'
    synced=await client.post('/engine-control/credentials',json={});assert synced.status_code==200;before=len(headers)
    for call in (lambda:service._whisper_single(str(audio)),lambda:service._voxtral_single(str(audio),None,None)):
     try:await call()
     except ValueError as error:assert ('key' in str(error).lower() or 'credential' in str(error).lower()) and ('required' in str(error).lower() or 'not configured' in str(error).lower()), 'Missing credential must have an actionable provider message'
     else:raise AssertionError('Cleared credentials must fail before sending any stale or empty authorization header')
    assert len(headers)==before
   finally:
    await service._openai.close();await service._mistral.close();await initial_openai.close();await initial_mistral.close()
  for name,test in [('chunk phases, durable bytes, resume status and offset conflict',chunks),('project readiness with absent and existing edit plan',readiness),('real SDK headers after secure sync, rotation and clearing',credentials)]:
   try:await test();cases.append({'name':name,'status':'PASS'});print('PASS '+name,flush=True)
   except Exception as error:cases.append({'name':name,'status':'FAIL','errorType':type(error).__name__,'detail':str(error)[:500]});print('FAIL '+name+': '+type(error).__name__,flush=True)
 await dispose_db();receipt={'status':'PASS' if all(x['status']=='PASS' for x in cases) else 'FAIL','scope':__doc__.strip(),'repo':str(repo),'cases':cases};(output/'receipt.json').write_text(json.dumps(receipt,indent=2));return receipt['status']=='PASS'
raise SystemExit(0 if asyncio.run(exercise()) else 1)

