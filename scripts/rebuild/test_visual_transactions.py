"""Main acceptance of actual SQLite visual transactions, with offline external fixtures."""
import asyncio
from contextlib import closing, AsyncExitStack
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

REPO = Path(sys.argv.pop(1)) if len(sys.argv)>1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[2]

async def exercise(case, root):
    sys.path.insert(0, str(REPO/'backend'/'app'))
    from desktop_native.paths import NativeDesktopPaths
    paths = NativeDesktopPaths.from_environment(data_root=root)
    paths.ensure_directories(); os.environ.update(paths.settings_environment())
    os.environ['RUNTIME_PROFILE']='desktop-native'; os.environ['EMBEDDING_DIMENSIONS']='3'
    from db.database import init_db, async_session, dispose_db
    from db.models import Video, Transcript, Segment, Scene, SegmentAction, Project, ProjectAsset, ProjectAssetKind, ProjectAssetRole
    from agents import visual_structure as visual
    from services.pdf_slides import pdf_slide_service
    from sqlalchemy import select
    await init_db()
    vid, sid, old_scene, tid, pid, aid = [uuid.uuid4() for _ in range(6)]
    media=root/'fixture.mp4'; media.write_bytes(b'offline fixture, never decoded')
    deck=root/'slides.pdf'; deck.write_bytes(b'offline fixture, never parsed')
    slide=case.startswith('slide')
    async with async_session() as db:
        if slide:
            db.add(Project(id=pid,title='Fixture')); await db.flush()
            db.add(ProjectAsset(id=aid,project_id=pid,filename='slides.pdf',original_filename='slides.pdf',file_path=str(deck),
                kind=ProjectAssetKind.SLIDE_DECK,role=ProjectAssetRole.SLIDES)); await db.flush()
        db.add(Video(id=vid,filename='fixture.mp4',original_filename='fixture.mp4',file_path=str(media),duration_seconds=20,
            project_id=pid if slide else None))
        await db.flush()
        for i in range(2):
            db.add(Segment(id=sid if i==0 else uuid.uuid4(),video_id=vid,segment_index=i,start_time=i*10,end_time=(i+1)*10,
                duration=10,text='Educational topic complete sentence.',summary='Educational topic',topic_label='Topic',
                scene_id=str(old_scene),slide_index=8,has_slide_change=True,filler_count=0))
        db.add(Scene(id=old_scene,video_id=vid,timestamp=3,scene_index=8,scene_type='old'))
        db.add(Transcript(id=tid,video_id=vid,full_text='Educational topic',words_json=[{'word':'Educational','start':0,'end':1}]))
        await db.commit()
    calls=[]
    def unlocked(label):
        with closing(sqlite3.connect(paths.database,timeout=.15)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            assert writer.execute('SELECT scene_type FROM scenes').fetchall()==[('old',)], 'Prior scene disappeared during compute'
            assert all(r==(8,1) for r in writer.execute('SELECT slide_index, has_slide_change FROM segments')), 'Prior flags changed during compute'
            writer.rollback()
        calls.append(label)
    async def concurrent():
        async with async_session() as other:
            row=await other.get(Segment,sid)
            row.filler_count=4; row.fluency_score=.7; row.action=SegmentAction.HIGHLIGHT
            row.teacher_action=SegmentAction.KEEP; row.teacher_note='preserve teacher'; row.is_teacher_modified=True
            if case=='stale':row.text='Teacher corrected source transcript'
            if case=='extra':other.add(Segment(id=uuid.uuid4(),video_id=vid,segment_index=2,start_time=20,end_time=21,duration=1,text='New source'))
            if case=='transcript-stale':
                transcript=await other.get(Transcript,tid); transcript.words_json=[{'word':'Changed','start':0,'end':1}]
            if case=='video-stale':
                video=await other.get(Video,vid); video.file_path=str(root/'changed.mp4')
            if case=='slide-stale':
                asset=await other.get(ProjectAsset,aid); asset.metadata_json={'slide_page_start':1,'slide_page_end':1}
            await other.commit()
    async def detect(*args):
        unlocked('cv'); await concurrent()
        if case=='cancel':raise asyncio.CancelledError()
        if case=='timeout':return [],True
        if case=='empty':return [],False
        clock=lambda v: SimpleNamespace(get_seconds=lambda:v)
        return [(clock(0),clock(10)),(clock(10),clock(20))],False
    async def thumbnail(**kwargs):
        unlocked('thumbnail'); Path(kwargs['output_path']).write_bytes(b'offline image fixture'); return kwargs['output_path']
    async def document(*args,**kwargs):
        unlocked('document'); await concurrent()
        return [{'page_number':1,'text':'Educational topic complete sentence.','image_path':str(root/'slide.png'),'width':1920,'height':1080}]
    async def matching(segments,pages,video_id,**kwargs):
        unlocked('llm')
        assert isinstance(kwargs['timed_words'],list) and not hasattr(segments[0],'_sa_instance_state')
        return {'slide_timeline':[{'start_time':0,'end_time':20,'slide_index':0,'block_title':'Topic','summary':'Educational topic',
            'transcript_excerpt':'Educational topic complete sentence.','slide_relevance':'direct','slide_relation':'related',
            'layout':'picture_in_picture','confidence':.9,'cue_type':'topic','reason':'Relevant slide'}]}
    rejected=case in ('stale','extra','transcript-stale','video-stale','slide-stale')
    try:
        async with async_session() as db, AsyncExitStack() as mocks:
            mocks.enter_context(patch.object(visual,'_detect_scenes_with_timeout',detect))
            mocks.enter_context(patch.object(visual.ffmpeg_service,'extract_frame',thumbnail))
            mocks.enter_context(patch.object(visual,'_vision_provider_id',return_value='offline-fixture'))
            if slide:
                mocks.enter_context(patch.object(visual,'_detect_camera_with_slides',return_value=True))
                mocks.enter_context(patch.object(pdf_slide_service,'extract_pdf_pages',document))
                mocks.enter_context(patch.object(visual,'_llm_slide_matching',matching))
            if case=='skip':mocks.enter_context(patch.object(visual,'_scene_detection_skip_reason',return_value='structure fixture'))
            if rejected:
                with unittest.TestCase().assertRaisesRegex(ValueError,'Stale visual'):
                    await visual.run_visual_structure_agent(vid,db)
            elif case=='cancel':
                with unittest.TestCase().assertRaises(asyncio.CancelledError):await visual.run_visual_structure_agent(vid,db)
            else:
                result=await visual.run_visual_structure_agent(vid,db)
                assert result['status']=='success'
            assert not db.in_transaction(), 'Agent retained transaction'
        async with async_session() as fresh:
            scenes=list((await fresh.execute(select(Scene).where(Scene.video_id==vid))).scalars())
            row=await fresh.get(Segment,sid)
            if rejected or case=='cancel':
                assert [s.id for s in scenes]==[old_scene] and row.slide_index==8 and row.scene_id==str(old_scene)
            elif slide:
                assert scenes==[] and row.slide_index==0 and result['slides_detected']==1
                assert result['editorial_blocks'] and result['document_preflight']
                assert calls==['document','llm']
            elif case in ('timeout','empty','skip'):
                assert scenes==[] and row.slide_index is None and not row.has_slide_change
                if case=='timeout':assert result['analysis_source']=='pyscenedetect_timeout_fallback'
                if case=='skip':assert result['analysis_source']=='structure_reference_skip' and calls==[]
            else:
                assert len(scenes)==2 and old_scene not in [s.id for s in scenes]
                assert row.scene_id in {str(s.id) for s in scenes} and row.slide_index==0
                assert calls==['cv','thumbnail','thumbnail']
            if case!='skip':
                assert row.filler_count==4 and row.fluency_score==.7 and row.action==SegmentAction.HIGHLIGHT
                assert row.teacher_action==SegmentAction.KEEP and row.teacher_note=='preserve teacher' and row.is_teacher_modified
        print('PASS',case,calls)
    finally:await dispose_db()

class VisualTransactionsTests(unittest.TestCase):
    def run_case(self,case):
        output=REPO/'.test-output'/'visual-transactions'; output.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=case+'-',dir=output) as temp:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(REPO),'--child',case,temp],cwd=REPO,
                env=os.environ.copy(),capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertIn('PASS '+case,result.stdout)
    def test_cv_thumbnails_release_writer_preserve_prior_and_concurrent_state(self):self.run_case('cv')
    def test_cancel_preserves_previous_scenes(self):self.run_case('cancel')
    def test_changed_segment_rejects_all_computed_visual_state(self):self.run_case('stale')
    def test_new_segment_rejects_incomplete_generation(self):self.run_case('extra')
    def test_changed_transcript_words_reject_old_alignment(self):self.run_case('transcript-stale')
    def test_changed_video_source_rejects_old_analysis(self):self.run_case('video-stale')
    def test_timeout_atomically_clears_prior_visual_state(self):self.run_case('timeout')
    def test_empty_detection_atomically_clears_prior_visual_state(self):self.run_case('empty')
    def test_structure_skip_commits_honest_result(self):self.run_case('skip')
    def test_slide_document_llm_release_writer_preserve_parallel_fields(self):self.run_case('slide')
    def test_changed_slide_scope_rejects_old_alignment(self):self.run_case('slide-stale')

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':asyncio.run(exercise(sys.argv[2],Path(sys.argv[3])))
    else:unittest.main(verbosity=2)
