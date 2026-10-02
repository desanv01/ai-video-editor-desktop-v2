"""Main-owned actual SQLite/ASGI regression for installed video status polling."""
import asyncio,json,os,sys,uuid
from pathlib import Path
REPO=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]
OUT=REPO/'.test-output'/'video-status'/uuid.uuid4().hex;OUT.mkdir(parents=True,exist_ok=False)
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('API_KEY'):os.environ.pop(k,None)
os.environ.update(RUNTIME_PROFILE='desktop-native',APP_STORAGE_ROOT=str(OUT/'profile'),AIVE_DESKTOP_DATA_ROOT=str(OUT/'profile'),TEMP_PATH=str(OUT/'temp'),CONFIG_PATH=str(OUT/'profile/Config'),LOG_PATH=str(OUT/'profile/Logs'),DESKTOP_DB_PATH=str(OUT/'profile/Config/engine.sqlite3'),DESKTOP_VECTOR_ROOT=str(OUT/'profile/VectorStore'),VIDEO_STORAGE_PATH=str(OUT/'profile/Exports'),DATABASE_URL='')
sys.path.insert(0,str(REPO/'backend/app'))
from fastapi import FastAPI
import httpx
from db.database import async_session,init_db,dispose_db
from db.models import Video,VideoStatus,EditPlan,Segment,SegmentAction
from api.routes.videos import router
from services.render_jobs import configure_render_job_store,create_render_job,update_render_job,complete_render_job,fail_render_job
from services.job_adapter import render_job
async def main():
 await init_db();configure_render_job_store(OUT/'render_jobs.json');app=FastAPI();app.include_router(router,prefix='/api/v1');results=[]
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
  for case,status in [('uploaded',VideoStatus.UPLOADED),('review',VideoStatus.AWAITING_REVIEW),('running',VideoStatus.RENDERING),('completed',VideoStatus.COMPLETED),('failed',VideoStatus.FAILED)]:
   vid=uuid.uuid4()
   async with async_session() as db:
    db.add(Video(id=vid,filename='controlled.mp4',original_filename='Controlled teacher lecture.mp4',file_path=str(OUT/'source.mp4'),duration_seconds=6,status=status,processed_video_path=str(OUT/'edited.mp4') if case=='completed' else None,error_message='Controlled failed render' if case=='failed' else None));await db.flush()
    db.add(Segment(video_id=vid,segment_index=0,start_time=0,end_time=2,text='Controlled teacher evidence',action=SegmentAction.KEEP,teacher_action=SegmentAction.CUT,is_teacher_modified=True,teacher_note='Retain lecturer decision'))
    if case!='uploaded':db.add(EditPlan(video_id=vid,plan_json=[],original_duration=6,estimated_duration=4,is_approved=case in {'running','completed'}))
    await db.commit()
   if case in {'running','completed','failed'}:
    job=create_render_job(str(vid),'mp4_720p')
    if case=='running':update_render_job(job['job_id'],str(vid),progress_percent=37,phase='native_semantic_composition')
    elif case=='completed':complete_render_job(job['job_id'],str(vid),{'output_path':str(OUT/'edited.mp4')})
    else:fail_render_job(job['job_id'],str(vid),'Controlled failed render')
   response=await client.get(f'/api/v1/videos/{vid}/status');assert response.status_code==200,(case,response.status_code,response.text)
   payload=response.json();assert payload['status']==status.value and payload['video_id']==str(vid)
   assert payload['job']['video_id']==str(vid)
   if case=='running':assert payload['workflow_state']=='exporting' and payload['job']['type']=='export' and payload['job']['state']=='running' and payload['job']['progress_percent']==37
   if case=='completed':assert payload['workflow_state']=='completed' and payload['job']['state']=='completed'
   if case=='failed':assert payload['workflow_state']=='failed' and payload['job']['state']=='failed' and payload['job']['retryable']
   segments=(await client.get(f'/api/v1/videos/{vid}/segments')).json();assert segments[0]['teacher_note']=='Retain lecturer decision' and segments[0]['teacher_action']=='cut'
   results.append({'case':case,'http':200,'workflowState':payload['workflow_state'],'jobState':payload['job']['state'],'teacherDecisionRetained':True})
  assert (await client.get(f'/api/v1/videos/{uuid.uuid4()}/status')).status_code==404
 # Actual adapter compatibility for older job-only callers and missing/present video identities.
 assert render_job(None,video_id='fallback') is None
 job={'job_id':'controlled-export','status':'running'}
 assert render_job(job)['video_id'] is None
 assert render_job(job,video_id='fallback')['video_id']=='fallback'
 assert render_job({**job,'video_id':'original'},video_id='fallback')['video_id']=='original'
 await dispose_db();(OUT/'acceptance.json').write_text(json.dumps({'status':'passed','scope':'Actual source native SQLite/ASGI status endpoints; controlled render-job states only, no actual render/provider/installed claim','cases':results,'missingVideo':404,'adapterCompatibility':True},indent=2),encoding='utf-8');print('PASS: video status API uploaded/review/running/completed/failed/missing, teacher persistence and legacy adapter compatibility')
asyncio.run(main())