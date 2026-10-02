"""Main acceptance: real SQLite, deterministic external work, no live providers."""
import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

REPO=Path(sys.argv.pop(1)) if len(sys.argv)>1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[2]

async def exercise(case,root):
    sys.path.insert(0,str(REPO/'backend'/'app'))
    from desktop_native.paths import NativeDesktopPaths
    paths=NativeDesktopPaths.from_environment(data_root=root)
    paths.ensure_directories();os.environ.update(paths.settings_environment())
    os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['EMBEDDING_DIMENSIONS']='3'
    from db.database import init_db,async_session,dispose_db
    from db.models import Video,Transcript,Segment,SegmentAction
    from sqlalchemy import select
    from agents import transcription,content_understanding,fluency
    await init_db()
    vid=uuid.uuid4();sid=uuid.uuid4()
    async with async_session() as db:
        db.add(Video(id=vid,filename='fixture.mp4',original_filename='fixture.mp4',file_path=str(root/'fixture.mp4'),duration_seconds=720))
        await db.commit()
        if case.startswith('fluency'):
            audio=root/'audio.wav';audio.write_bytes(b'fixture, never decoded')
            video=await db.get(Video,vid);video.audio_path=str(audio)
            for i in range(9):
                db.add(Segment(id=sid if i==0 else uuid.uuid4(),video_id=vid,segment_index=i,
                    start_time=i*10,end_time=(i+1)*10,duration=10,text='um educational lesson',filler_count=0))
            await db.commit()
        elif case=='content':
            db.add(Transcript(id=uuid.uuid4(),video_id=vid,full_text='lecture',
                segments_json=[{'start':i*60,'end':(i+1)*60,'text':'important lesson '*15,'speaker':'Teacher'} for i in range(12)]))
            await db.commit()
    calls=[]
    def unlocked(label):
        with closing(sqlite3.connect(paths.database,timeout=0.15)) as writer:
            writer.execute('BEGIN IMMEDIATE');writer.rollback()
        calls.append(label)
    async def acoustic(**kwargs):
        unlocked('acoustic');return [{'start':0,'end':1,'duration':1}]
    async def chat(*args,**kwargs):
        unlocked('chat')
        if case.startswith('fluency') and calls.count('chat')==1:
            async with async_session() as other:
                seg=await other.get(Segment,sid)
                seg.slide_index=7;seg.scene_id='teacher-visual';seg.has_slide_change=True
                seg.teacher_action=SegmentAction.KEEP;seg.teacher_note='preserve teacher';seg.is_teacher_modified=True
                if case=='fluency-stale':seg.text='teacher corrected the transcript'
                await other.commit()
        return {'segments':[{'segment_index':i,'topic_label':'Lesson','summary':'Same semantics','importance_score':0.8,
            'segment_type':'core_content','filler_count':2,'filler_words':['um','uh'],'fluency_score':0.75,'has_repetition':True} for i in range(12)]}
    async def search(**kwargs):unlocked('rag');return []
    async def extract(**kwargs):unlocked('extract');return kwargs['output_path']
    async def asr(**kwargs):
        unlocked('asr')
        if case=='transcription-cancel':raise asyncio.CancelledError()
        return {'text':'educational lecture','words':[],'segments':[{'start':0,'end':10,'text':'educational lecture'}],
                'duration':10,'provider':'fixture','transcription_route':'fixture-route','speakers':['Teacher']}
    try:
        async with async_session() as db:
            with patch.object(fluency.ffmpeg_service,'detect_silence',acoustic),patch.object(fluency.llm_service,'chat_json',chat),\
                 patch.object(fluency.llm_service,'provider_id_for_kind',return_value='fixture-chat'),\
                 patch.object(content_understanding.rag_service,'search',search),\
                 patch.object(transcription.ffmpeg_service,'extract_audio',extract),\
                 patch.object(transcription.transcription_service,'transcribe',asr):
                if case.startswith('fluency'):
                    if case=='fluency-stale':
                        with unittest.TestCase().assertRaisesRegex(ValueError,'Stale fluency'):
                            await fluency.run_fluency_agent(vid,db)
                    else:
                        result=await fluency.run_fluency_agent(vid,db)
                        assert result['segments_updated']==9 and result['batches_attempted']==2
                elif case=='content':
                    result=await content_understanding.run_content_understanding_agent(vid,db)
                    assert result['segments_analyzed']>=6 and len(result['chapters'])==1
                elif case=='transcription-cancel':
                    with unittest.TestCase().assertRaises(asyncio.CancelledError):
                        await transcription.run_transcription_agent(vid,db)
                else:
                    result=await transcription.run_transcription_agent(vid,db)
                    assert result['provider']=='fixture' and result['transcription_route']=='fixture-route'
                    assert result['word_count']==2
            assert not db.in_transaction()
        async with async_session() as fresh:
            if case.startswith('fluency'):
                seg=await fresh.get(Segment,sid)
                assert (seg.slide_index,seg.scene_id,seg.has_slide_change)==(7,'teacher-visual',True)
                assert seg.teacher_note=='preserve teacher' and seg.teacher_action==SegmentAction.KEEP and seg.is_teacher_modified
                assert seg.filler_count==(0 if case=='fluency-stale' else 2)
                assert calls.count('chat')==2
            elif case=='content':
                rows=(await fresh.execute(select(Segment).where(Segment.video_id==vid))).scalars().all()
                assert len(rows)==result['segments_analyzed'] and all(s.speaker=='Teacher' for s in rows)
                assert calls.count('chat')>=2 and calls.count('rag')>=2
            else:
                row=(await fresh.execute(select(Transcript).where(Transcript.video_id==vid))).scalar_one_or_none()
                if case=='transcription-cancel':assert row is None
                else:
                    video=await fresh.get(Video,vid)
                    assert row.word_count==2 and video.audio_path.endswith('_audio.wav') and video.duration_seconds==10
        print('PASS',case,'external operations',calls)
    finally:
        await dispose_db()

class AgentTransactionsTests(unittest.TestCase):
    def run_case(self,case):
        output=REPO/'.test-output'/'agent-transactions';output.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=case+'-',dir=output) as temp:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(REPO),'--child',case,temp],
                cwd=REPO,env=os.environ.copy(),capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertIn('PASS '+case,result.stdout)
    def test_transcription_releases_writer_across_extract_and_asr(self):self.run_case('transcription')
    def test_transcription_cancellation_propagates_without_partial_transcript(self):self.run_case('transcription-cancel')
    def test_content_releases_writer_across_multiple_rag_llm_batches(self):self.run_case('content')
    def test_fluency_batches_preserve_concurrent_visual_and_teacher_edits(self):self.run_case('fluency')
    def test_fluency_rejects_changed_inputs_without_partial_results(self):self.run_case('fluency-stale')

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':asyncio.run(exercise(sys.argv[2],Path(sys.argv[3])))
    else:unittest.main(verbosity=2)
