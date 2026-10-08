from pathlib import Path
import argparse,os,sys,json,asyncio,sqlite3,hashlib
from datetime import datetime,timedelta
from types import SimpleNamespace
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--installed-snapshot',type=Path);a=p.parse_args();a.output.mkdir(exist_ok=False)
source=a.installed_snapshot
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('_API_KEY') or k in ['DATABASE_URL','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT']:os.environ.pop(k,None)
sys.path[:0]=[str(a.repo/'backend'),str(a.repo/'backend/app')]
from desktop_native.paths import NativeDesktopPaths
paths=NativeDesktopPaths.from_environment(data_root=a.output/'profile');paths.ensure_directories();os.environ.update(paths.settings_environment());os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['EMBEDDING_DIMENSIONS']='3'
if source:
 with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(paths.database) as dest:src.backup(dest)
from db.database import async_session,dispose_db,init_db
from db.models import Video,Segment,EditPlan,VideoStatus,SegmentAction
from sqlalchemy import select
from services.renderer import generate_quality_report
from services.evaluation_metrics import build_evaluation_metrics
from services.transcript_edit_decisions import build_synced_timeline_plan,create_transcript_cut_decision
from services.export_artifacts import build_before_after_comparison,build_metrics_summary_artifact,build_evidence_markdown
cases=[];vid='c2385141-4cc9-40b6-ae13-42f5c1aa5d86'
async def main():
 if not source:
  await init_db()
  async with async_session() as seed:
   seed.add(Video(id=vid,filename='fixture.mp4',original_filename='Controlled lecture',file_path=str(a.output/'fixture.mp4'),duration_seconds=6,status=VideoStatus.AWAITING_REVIEW,created_at=datetime(2026,10,2)))
   await seed.flush()
   seed.add(EditPlan(video_id=vid,original_duration=6,estimated_duration=6,segments_total=3,segments_keep=3,segments_cut=0,segments_highlight=0,plan_json={}))
   for i in range(3):seed.add(Segment(video_id=vid,segment_index=i,start_time=i*2,end_time=i*2+2,duration=2,text=f'Part{i}',action=SegmentAction.KEEP,teacher_action=SegmentAction.CUT if i==1 else None,is_teacher_modified=i==1,teacher_note='Teacher cut' if i==1 else None))
   await seed.commit()
 async with async_session() as db:
  video=await db.get(Video,vid);plan=(await db.execute(select(EditPlan).where(EditPlan.video_id==vid))).scalar_one();segments=list((await db.execute(select(Segment).where(Segment.video_id==vid).order_by(Segment.segment_index))).scalars())
  saved_created_at=video.created_at
  async def test(name,fn):
   try:await fn();cases.append({'case':name,'status':'passed'})
   except AssertionError as e:cases.append({'case':name,'status':'failed','error':str(e)})
  async def current():
   q=await generate_quality_report(vid,db);sync=build_synced_timeline_plan(plan=plan,segments=segments,duration_seconds=video.duration_seconds);expected=sync['export_plan']['estimated_output_duration_seconds'];assert expected==4
   b=build_before_after_comparison(video=video,plan=plan,segments=segments,plan_payload=plan.plan_json,quality_report=q);m=build_metrics_summary_artifact(q)
   assert q['estimated_duration_seconds']==4,'Current canonical teacher-cut estimate must be4, not stale6'
   assert q['time_saved_seconds']==2 and abs(q['reduction_percent']-100/3)<0.1
   assert q['segments_cut']==1 and q['segments_keep']==2
   assert b['after']['removed_duration_seconds']==2 and m['duration']['time_saved_seconds']==2
  async def word_cut():
   prior=plan.plan_json
   create_transcript_cut_decision(plan=plan,timeline_words=[{'text':'Welcome','start_time':0.,'end_time':1.}],word_start_index=0,word_end_index=0)
   q=await generate_quality_report(vid,db)
   assert q['estimated_duration_seconds']==3 and q['time_saved_seconds']==3
   assert q['evaluation_metrics']['duration_reduction']['estimated_duration_seconds']==3
   plan.plan_json=prior
   assert '- Processing time: n/a' in build_evidence_markdown({'metrics_summary':{'processing_time_seconds':None}})
  async def zero():
   for s in segments:s.teacher_action=type(s.action)('cut');s.is_teacher_modified=True
   m=build_evaluation_metrics(video=video,plan=plan,segments=segments,plan_payload=plan.plan_json,actual_output_duration_seconds=0.25)
   assert m['duration_reduction']['estimated_duration_seconds']==0,'All-cut canonical estimate must preserve valid zero'
   assert m['duration_reduction']['time_saved_seconds']==6
   assert m['duration_reduction']['actual_output_duration_seconds']==0.25
   await db.rollback()
  async def elapsed():
   v=SimpleNamespace(created_at=saved_created_at,updated_at=saved_created_at+timedelta(days=10),duration_seconds=6)
   p=SimpleNamespace(original_duration=6,estimated_duration=6,created_at=saved_created_at+timedelta(seconds=50),updated_at=saved_created_at+timedelta(days=10),plan_json={})
   m=build_evaluation_metrics(video=v,plan=p,segments=[],plan_payload={});assert m['processing_time']['total_seconds'] is None,'Record lifetime must not be labeled measured processing time';assert m['summary']['processing_time_seconds'] is None
  await test('actual-retained-teacher-report-and-related-artifacts',current);await test('word-cut-and-markdown-unavailable-timing',word_cut);await test('all-cut-zero-estimate-distinct-from-actual-render',zero);await test('export-timestamp-change-not-processing-time',elapsed)
 await dispose_db()
asyncio.run(main());receipt={'scope':('Copied installed SQLite' if source else 'Fresh native SQLite fixture')+'; real report functions/canonical planning, no provider calls or installed-profile writes','cases':cases,'status':'passed' if all(c['status']=='passed' for c in cases) else 'failed'};(a.output/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2));sys.exit(0 if receipt['status']=='passed' else 1)

