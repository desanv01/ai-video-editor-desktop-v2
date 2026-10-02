"""Main-owned native SQLite/API acceptance for original transcript exports."""
import asyncio, csv, io, json, os, sys, uuid, ast
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
OUT=REPO/'.test-output'/'transcript-api'/uuid.uuid4().hex
OUT.mkdir(parents=True,exist_ok=False)
for k in list(os.environ):
    if k.startswith('AIVE_') or k.endswith('API_KEY'): os.environ.pop(k,None)
os.environ.update({'RUNTIME_PROFILE':'desktop-native','APP_STORAGE_ROOT':str(OUT/'profile'),
 'AIVE_DESKTOP_DATA_ROOT':str(OUT/'profile'),'TEMP_PATH':str(OUT/'temp'),
 'CONFIG_PATH':str(OUT/'profile/Config'),'LOG_PATH':str(OUT/'profile/Logs'),
 'DESKTOP_DB_PATH':str(OUT/'profile/Config/engine.sqlite3'),
 'DESKTOP_VECTOR_ROOT':str(OUT/'profile/VectorStore'),'DATABASE_URL':''})
sys.path.insert(0,str(REPO/'backend/app'))
from fastapi import FastAPI
import httpx
from db.database import async_session, init_db, dispose_db
from db.models import Video, Transcript, Segment, SegmentAction
from api.routes.videos import router

async def main():
    await init_db()
    ident,empty,missing=uuid.uuid4(),uuid.uuid4(),uuid.uuid4()
    original='Original lecture — pengajaran 中文. Keep the filler um and every sentence.'
    raw=[{'start':1.25,'end':9.875,'speaker':'Teacher 1','text':original}]
    words=[{'word':'um','start':3.1,'end':3.3}]
    async with async_session() as db:
        db.add_all([Video(id=ident,filename='stored.mp4',original_filename='Kuliah 中文\r\nUnsafe.mp4',file_path=str(OUT/'input.mp4'),duration_seconds=10),
                    Video(id=empty,filename='empty.mp4',original_filename='Empty.mp4',file_path=str(OUT/'empty.mp4'))])
        await db.flush()
        db.add(Transcript(video_id=ident,full_text=original,segments_json=raw,words_json=words,asr_provider='whisper',language='ms',word_count=14))
        seg=Segment(video_id=ident,segment_index=0,start_time=0,end_time=1,text='Edited text must never replace original',action=SegmentAction.KEEP,teacher_action=SegmentAction.CUT,is_teacher_modified=True,teacher_note='Teacher decision retained')
        db.add(seg); await db.commit(); segment_id=seg.id
    app=FastAPI(); app.include_router(router,prefix='/api/v1')
    results=[]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        for fmt in ('txt','timestamped_txt','json','csv'):
            response=await client.get(f'/api/v1/videos/{ident}/transcript/export',params={'format':fmt})
            assert response.status_code==200,(fmt,response.status_code,response.text)
            assert original in response.text and 'Edited text must' not in response.text
            assert response.headers['cache-control']=='private, no-store'
            assert response.headers['x-content-type-options']=='nosniff'
            disposition=response.headers['content-disposition']
            assert disposition.startswith("attachment; filename*=UTF-8''") and '\r' not in disposition and '\n' not in disposition
            if fmt=='txt': assert response.text==original
            if fmt=='json':
                payload=response.json(); assert payload['segments']==raw and payload['words']==words and payload['timeline']=='original_recording'
            if fmt=='csv':
                rows=list(csv.DictReader(io.StringIO(response.text))); assert len(rows)==1 and rows[0]['start_seconds']=='1.25' and rows[0]['end_seconds']=='9.875'
            results.append({'format':fmt,'status':response.status_code,'content_type':response.headers['content-type'],'bytes':len(response.content)})
        catalog=(await client.get(f'/api/v1/videos/{ident}/exports')).json()
        files=catalog.get('files',catalog.get('exports',catalog))
        for key in ('original_transcript_txt','original_transcript_timestamped_txt','original_transcript_json','original_transcript_segments_csv'):
            assert files[key]['available'] and files[key]['timeline']=='original_recording',(key,catalog)
        for video in (empty,missing):
            response=await client.get(f'/api/v1/videos/{video}/transcript/export'); assert response.status_code==404
        assert (await client.get(f'/api/v1/videos/{ident}/transcript/export?format=srt')).status_code==422
        assert (await client.get('/api/v1/videos/not-a-uuid/transcript/export')).status_code==422
        empty_catalog=(await client.get(f'/api/v1/videos/{empty}/exports')).json()
        empty_files=empty_catalog.get('files',empty_catalog.get('exports',empty_catalog))
        assert not empty_files['original_transcript_txt']['available']
    async with async_session() as db:
        seg=await db.get(Segment,segment_id)
        assert seg.teacher_action==SegmentAction.CUT and seg.is_teacher_modified and seg.teacher_note=='Teacher decision retained'
    await dispose_db()
    (OUT/'acceptance.json').write_text(json.dumps({'status':'passed','runtime':'source native SQLite / actual ASGI routes','formats':results,'teacher_override_unchanged':True},indent=2),encoding='utf-8')
    print('PASS: four original formats through native SQLite API, catalog, errors, teacher override')

asyncio.run(main())
