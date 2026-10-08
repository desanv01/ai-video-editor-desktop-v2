"""Main acceptance: planning, pipeline ordering and callers on actual SQLite."""
import asyncio
from contextlib import AsyncExitStack, closing
from copy import deepcopy
from datetime import datetime
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
    paths=NativeDesktopPaths.from_environment(data_root=root);paths.ensure_directories();os.environ.update(paths.settings_environment())
    os.environ['RUNTIME_PROFILE']='desktop-native';os.environ['EMBEDDING_DIMENSIONS']='3'
    from db.database import init_db,async_session,dispose_db
    from db.models import Video,VideoStatus,Transcript,Segment,SegmentAction,SegmentType,EditPlan,CourseMaterial
    from agents import edit_planner as planner,orchestrator as pipeline
    from api.routes import videos as callers
    from services import clean_tools
    from sqlalchemy import select
    await init_db()
    vid,sid,pid,mid=[uuid.uuid4() for _ in range(4)]
    pipeline_case=case.startswith('pipeline')
    async with async_session() as db:
        db.add(Video(id=vid,filename='fixture.mp4',original_filename='fixture.mp4',file_path=str(root/'fixture.mp4'),duration_seconds=160))
        await db.flush()
        if not pipeline_case:
            for i in range(16):
                db.add(Segment(id=sid if i==0 else uuid.uuid4(),video_id=vid,segment_index=i,start_time=i*10,end_time=(i+1)*10,
                    duration=10,text='Important educational concept.',summary='Concept',topic_label='Topic',importance_score=.75,
                    segment_type=SegmentType.CORE_CONTENT,fluency_score=.8,action=SegmentAction.KEEP,action_reason='old decision'))
        db.add(Transcript(id=uuid.uuid4(),video_id=vid,full_text='Important educational concept.',words_json=[],
            segments_json=[{'start':0,'end':160,'text':'Important educational concept.'}]))
        if not pipeline_case:
            db.add(EditPlan(id=pid,video_id=vid,plan_json={'teacher_marker':'old plan'},is_approved=True,
                approved_at=datetime(2026,1,1),teacher_notes='old notes',segments_total=16,original_duration=160,estimated_duration=160))
        db.add(CourseMaterial(id=mid,filename='fixture.txt',file_path=str(root/'fixture.txt'),file_type='txt',content_text='old content',chunk_count=7,is_embedded=True))
        await db.commit()
    calls=[];clean_calls=[];guard_differences=[]
    def unlocked(label):
        with closing(sqlite3.connect(paths.database,timeout=.15)) as writer:
            writer.execute('BEGIN IMMEDIATE');writer.rollback()
        calls.append(label)
    async def teacher():
        async with async_session() as other:
            plan=(await other.execute(select(EditPlan).where(EditPlan.video_id==vid))).scalar_one()
            plan.plan_json={'teacher_marker':'new plan'};plan.teacher_notes='concurrent teacher';plan.is_approved=True;plan.approved_at=datetime(2026,2,2)
            row=(await other.execute(select(Segment).where(Segment.video_id==vid).order_by(Segment.segment_index))).scalars().first()
            row.teacher_action=SegmentAction.HIGHLIGHT;row.teacher_note='teacher decision';row.is_teacher_modified=True
            await other.commit()
    async def chat(*args,**kwargs):
        unlocked('chat')
        if calls.count('chat')==1:
            if case=='plan-stale':await teacher()
            if case=='plan-cancel':raise asyncio.CancelledError()
        return {'decisions':[{'segment_index':i,'action':'keep','layout_mode':'pip_slide','confidence':.95,'reason':'Core educational content'} for i in range(16)],'warnings':[]}
    def clean(**kwargs):
        unlocked('clean');clean_calls.append(kwargs['profile_id'])
        assert not hasattr(kwargs['plan'],'_sa_instance_state') and not hasattr(kwargs['segments'][0],'_sa_instance_state')
        if case=='clean-during':
            with closing(sqlite3.connect(paths.database,timeout=.15)) as writer:
                writer.execute("UPDATE edit_plans SET teacher_notes='concurrent teacher',is_approved=1,plan_json=?",('{"teacher_marker":"new plan"}',))
                writer.execute("UPDATE segments SET teacher_note='teacher decision',is_teacher_modified=1")
                writer.commit()
        kwargs['plan'].plan_json={'automatic_clean_marker':True};kwargs['plan'].estimated_duration=123
        kwargs['segments'][0].teacher_action=SegmentAction.CUT;kwargs['segments'][0].teacher_note='automatic suggestion'
        return {'summary':{'fixture':True}}
    async def ensure():unlocked('ensure')
    async def ingest(**kwargs):
        unlocked('ingest'); assert kwargs['target_duration']==60 if 'target_duration' in kwargs else True
        if case=='material-stale':
            async with async_session() as other:
                material=await other.get(CourseMaterial,mid);material.content_text='new content';material.chunk_count=99;await other.commit()
        if case=='material-fail':raise RuntimeError('offline fixture failure')
        return 3
    try:
        async with AsyncExitStack() as mocks:
            if case=='clean-during':
                original_matches=planner._matches_snapshot
                def diagnosed_matches(row,saved,fields):
                    matched=original_matches(row,saved,fields)
                    if not matched:
                        guard_differences.append({
                            'row':type(row).__name__,
                            'fields':[(key,repr(getattr(row,key,None))[:500],repr(getattr(saved,key,None))[:500])
                                      for key in fields if getattr(row,key,None)!=getattr(saved,key,None)],
                        })
                    return matched
                mocks.enter_context(patch.object(planner,'_matches_snapshot',diagnosed_matches))
            mocks.enter_context(patch.object(planner.llm_service,'chat_json',chat))
            mocks.enter_context(patch.object(planner.llm_service,'provider_id_for_kind',return_value='offline-fixture'))
            mocks.enter_context(patch.object(pipeline.rag_service,'ensure_collection',ensure))
            mocks.enter_context(patch.object(pipeline.rag_service,'ingest_transcript',ingest))
            mocks.enter_context(patch.object(callers.rag_service,'ingest_course_material',ingest))
            if case.startswith('material'):
                await callers._embed_material_bg(str(mid),'fixture.txt',[{'page_number':1,'text':'old content'}])
            elif case=='caller':
                async def settings(db):
                    await db.execute(select(Video).where(Video.id==vid));calls.append('settings')
                async def run(video_id,db):
                    assert not db.in_transaction();unlocked('caller-pipeline');return {'status':'awaiting_review'}
                mocks.enter_context(patch.object(callers,'load_and_apply_persisted_ai_settings',settings))
                mocks.enter_context(patch.object(callers,'run_processing_pipeline',run))
                await callers._process_video_bg(str(vid))
                assert calls==['settings','ensure','caller-pipeline']
            elif pipeline_case:
                ready=asyncio.Event();entered=set();session_ids={};completed=set()
                async def transcribe(video_id,db):
                    unlocked('A1');return {'status':'success'}
                async def content(video_id,db):
                    unlocked('A2')
                    db.add(Segment(id=sid,video_id=vid,segment_index=0,start_time=0,end_time=160,duration=160,text='Important concept.',
                        topic_label='Topic',summary='Concept',importance_score=.75,segment_type=SegmentType.CORE_CONTENT,fluency_score=.8))
                    return {'status':'success'}
                async def parallel(label,db):
                    unlocked(label);assert calls.index('A2')<calls.index(label)
                    assert (await db.execute(select(Segment).where(Segment.video_id==vid))).scalars().first() is not None
                    await db.commit();session_ids[label]=id(db);entered.add(label)
                    if len(entered)==2:ready.set()
                    await asyncio.wait_for(ready.wait(),5);completed.add(label)
                async def fluency(video_id,db):
                    await parallel('A3',db)
                    row=await db.get(Segment,sid);row.filler_count=2;return {'status':'success'}
                async def visual(video_id,db):
                    await parallel('A4',db)
                    return {'status':'success','slide_timeline':[],'editorial_blocks':[],'analysis_source':'offline-fixture'}
                async def plan(video_id,db):
                    assert completed=={'A3','A4'} and session_ids['A3']!=session_ids['A4'] and id(db) not in session_ids.values()
                    unlocked('A5');result=await planner.run_edit_planner_agent(video_id,db)
                    if case=='pipeline-after-plan':await teacher()
                    return result
                original_commit=pipeline.commit_native
                async def commit(db):
                    is_envelope=any(isinstance(row,EditPlan) and isinstance(row.plan_json,dict) and 'visual_analysis' in row.plan_json for row in db.identity_map.values())
                    await original_commit(db)
                    if case=='pipeline-after-envelope' and is_envelope and 'after-envelope' not in calls:
                        calls.append('after-envelope');await teacher()
                mocks.enter_context(patch.object(pipeline,'run_transcription_agent',transcribe))
                mocks.enter_context(patch.object(pipeline,'run_content_understanding_agent',content))
                mocks.enter_context(patch.object(pipeline,'run_fluency_agent',fluency))
                mocks.enter_context(patch.object(pipeline,'run_visual_structure_agent',visual))
                mocks.enter_context(patch.object(pipeline,'run_edit_planner_agent',plan))
                mocks.enter_context(patch.object(pipeline,'commit_native',commit))
                mocks.enter_context(patch.object(clean_tools,'apply_clean_suggestions',clean))
                mocks.enter_context(patch.object(pipeline,'render_final_video',side_effect=AssertionError('Processing must never render')))
                async with async_session() as db:
                    result=await pipeline.run_processing_pipeline(str(vid),db)
                    assert result['status']=='awaiting_review',result
                    if case!='pipeline':assert result['review_required'] is True and clean_calls==[],result
                    else:assert clean_calls==['conservative'] and not result.get('review_required'),result
                    assert not db.in_transaction() and not db.info
                assert calls[:3]==['A1','ingest','A2'],calls
            else:
                async with async_session() as db:
                    if case=='plan-stale':
                        with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):await planner.run_edit_planner_agent(str(vid),db)
                    elif case=='plan-cancel':
                        with unittest.TestCase().assertRaises(asyncio.CancelledError):await planner.run_edit_planner_agent(str(vid),db)
                    else:
                        result=await planner.run_edit_planner_agent(str(vid),db)
                        assert result['status']=='success' and result['segments_total']==16 and calls.count('chat')==2
                        assert result['chat_provider']=='offline-fixture' and len(result['chapters'])==1
                        if case=='guard-after-plan':
                            await teacher()
                            with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):await planner._read_guarded_native_plan(db,str(vid))
                        elif case=='clean-before':
                            await teacher()
                            with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):await pipeline._run_native_auto_clean(str(vid),db,clean)
                            assert clean_calls==[]
                        elif case=='clean-during':
                            with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):await pipeline._run_native_auto_clean(str(vid),db,clean)
                            assert clean_calls==['conservative'], {'stage':'clean callback never reached','guard_differences':guard_differences,'calls':calls}
                        elif case=='clean':
                            await pipeline._run_native_auto_clean(str(vid),db,clean);assert clean_calls==['conservative'] and not db.info
                    assert not db.in_transaction()
        async with async_session() as fresh:
            material=await fresh.get(CourseMaterial,mid)
            if case.startswith('material'):
                if case=='material-stale':assert material.content_text=='new content' and material.chunk_count==99 and material.is_embedded
                elif case=='material-fail':assert material.chunk_count==7 and not material.is_embedded
                else:assert material.chunk_count==3 and material.is_embedded
            elif case!='caller':
                plan=(await fresh.execute(select(EditPlan).where(EditPlan.video_id==vid))).scalar_one()
                if case in ('plan-stale','guard-after-plan','clean-before','clean-during','pipeline-after-plan','pipeline-after-envelope'):
                    assert plan.plan_json=={'teacher_marker':'new plan'} and plan.teacher_notes=='concurrent teacher' and plan.is_approved
                    row=await fresh.get(Segment,sid);assert row.teacher_note=='teacher decision' and row.is_teacher_modified
                    if case=='plan-stale':assert row.action_reason=='old decision'
                elif case=='plan-cancel':assert plan.plan_json=={'teacher_marker':'old plan'} and plan.is_approved
                elif case in ('clean','pipeline'):assert plan.plan_json=={'automatic_clean_marker':True} and plan.estimated_duration==123
                else:assert not plan.is_approved and plan.approved_at is None and plan.segments_total==16 and plan.teacher_notes=='old notes'
        print('PASS',case,calls)
    finally:await dispose_db()

class PlanTransactionsTests(unittest.TestCase):
    def run_case(self,case):
        output=REPO/'.test-output'/'plan-transactions';output.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=case+'-',dir=output) as temp:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(REPO),'--child',case,temp],cwd=REPO,
                env=os.environ.copy(),capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr);self.assertIn('PASS '+case,result.stdout)
    def test_planner_batches_release_writer_and_commit_complete_plan(self):self.run_case('plan')
    def test_teacher_changes_during_planning_preserved_without_partial_decisions(self):self.run_case('plan-stale')
    def test_cancel_preserves_existing_approved_plan(self):self.run_case('plan-cancel')
    def test_teacher_changes_after_plan_reject_envelope_entry(self):self.run_case('guard-after-plan')
    def test_teacher_approval_before_clean_skips_all_automatic_mutation(self):self.run_case('clean-before')
    def test_teacher_edit_during_off_thread_clean_preserved(self):self.run_case('clean-during')
    def test_clean_computes_detached_then_commits_atomic_result(self):self.run_case('clean')
    def test_pipeline_committed_order_parallel_sessions_stops_before_render(self):self.run_case('pipeline')
    def test_pipeline_teacher_change_after_plan_requires_review(self):self.run_case('pipeline-after-plan')
    def test_pipeline_teacher_change_after_envelope_requires_review(self):self.run_case('pipeline-after-envelope')
    def test_material_embedding_has_no_writer_across_rag(self):self.run_case('material')
    def test_material_changed_during_embedding_preserves_new_state(self):self.run_case('material-stale')
    def test_material_failure_marks_only_unchanged_source(self):self.run_case('material-fail')
    def test_processing_caller_releases_settings_transaction_before_rag(self):self.run_case('caller')

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':asyncio.run(exercise(sys.argv[2],Path(sys.argv[3])))
    else:unittest.main(verbosity=2)
