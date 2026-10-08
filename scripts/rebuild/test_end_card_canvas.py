"""Actual native SQLite/managed-media end-card render regression; no providers."""
from pathlib import Path
import argparse,asyncio,json,os,sys,uuid,subprocess
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--ffmpeg-root',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
for k in list(os.environ):
 if k.startswith('AIVE_') or k.endswith('_API_KEY') or k in ['DATABASE_URL','DESKTOP_DB_PATH','DESKTOP_VECTOR_ROOT']:os.environ.pop(k,None)
sys.path[:0]=[str(a.repo/'backend'),str(a.repo/'backend/app')]
from desktop_native.paths import NativeDesktopPaths
paths=NativeDesktopPaths.from_environment(data_root=a.output/'profile');paths.ensure_directories();os.environ.update(paths.settings_environment());os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['EMBEDDING_DIMENSIONS']='3';os.environ['FFMPEG_HARDWARE_ACCELERATION']='cpu';os.environ['FFMPEG_BINARY_PATH']=str((a.ffmpeg_root/'bin/ffmpeg.exe').resolve());os.environ['FFPROBE_BINARY_PATH']=str((a.ffmpeg_root/'bin/ffprobe.exe').resolve())
from db.database import init_db,async_session,dispose_db
from db.models import Video,VideoStatus,Segment,SegmentAction,EditPlan
from services.edit_plan_payload import update_end_cards,update_caption_policy
from services.export_presets import get_export_preset
from services.semantic_render_plan import build_semantic_render_plan,with_semantic_render_plan
from services.renderer import render_final_video
source=paths.uploads/'lecture.mp4';subprocess.run([os.environ['FFMPEG_BINARY_PATH'],'-v','error','-f','lavfi','-i','color=c=blue:s=320x180:r=30','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],capture_output=True,check=True)
record={'scope':__doc__.strip(),'status':'running'}
async def main():
 await init_db();vid=uuid.uuid4()
 try:
  async with async_session() as db:
   v=Video(id=vid,filename=source.name,original_filename='Owned one-second lecture',file_path=str(source),duration_seconds=1,status=VideoStatus.AWAITING_REVIEW);db.add(v);await db.flush()
   segment=Segment(video_id=vid,segment_index=0,start_time=0,end_time=1,duration=1,text='Owned lecture',action=SegmentAction.KEEP,is_teacher_modified=False);db.add(segment);await db.flush()
   payload={'export_metadata':{'selected_preset':get_export_preset('mp4_720p'),'selected_preset_id':'mp4_720p'}};payload=update_caption_policy(payload,{'enabled':False,'appearance':'off','export_behavior':'none'});payload=update_end_cards(payload,[{'id':'owned-card','enabled':True,'card_type':'lecture_summary','title':'OWNED RECAP','body':'End card at correct dimensions','duration_seconds':2}]);plan=EditPlan(video_id=vid,original_duration=1,estimated_duration=1,segments_total=1,segments_keep=1,is_approved=True,plan_json=payload);db.add(plan);await db.flush();plan.plan_json=with_semantic_render_plan(plan.plan_json,build_semantic_render_plan(video=v,plan=plan,segments=[segment],transcript=None,assets=[]));await db.commit()
   result=await render_final_video(str(vid),db);await db.commit();assert result['status']=='success';assert result['end_card_count']==1;assert abs(result['output_duration']-3)<.15;record['result']=result;media=json.loads(subprocess.run([os.environ['FFPROBE_BINARY_PATH'],'-v','error','-show_entries','format=duration:stream=codec_type,width,height,duration','-of','json',result['output_path']],capture_output=True,text=True,check=True).stdout);vstream=next(x for x in media['streams'] if x['codec_type']=='video');astream=next(x for x in media['streams'] if x['codec_type']=='audio');assert vstream['width']==1280 and vstream['height']==720;assert abs(float(vstream['duration'])-float(astream['duration']))<.1;record['media']=media;record['status']='PASS'
 except Exception as e:record['status']='FAIL';record['error']=str(e);raise
 finally:await dispose_db();(a.output/'receipt.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps({'status':record['status'],'scope':record['scope']},indent=2),flush=True)
asyncio.run(main())
