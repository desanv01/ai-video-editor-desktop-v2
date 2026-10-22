"""Main acceptance: planning, pipeline ordering and callers on actual SQLite."""
import asyncio
import hashlib
from importlib import metadata
import json
import platform
from contextlib import AsyncExitStack, closing
from copy import deepcopy
from datetime import datetime, timedelta
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

# Optional durable report is restricted to contained validation output. The child
# also emits one JSON record on stdout, including when its existing assertions fail.
DIAGNOSTIC_REPORT = None
if '--diagnostic-report' in sys.argv:
    report_index = sys.argv.index('--diagnostic-report')
    DIAGNOSTIC_REPORT = Path(sys.argv[report_index + 1]).resolve()
    del sys.argv[report_index:report_index + 2]
    validation_root = Path('C:/Users/Dv/Desktop/ai-video-editor-standalone-release-work/rebuild/validation').resolve()
    if not DIAGNOSTIC_REPORT.is_relative_to(validation_root):
        raise ValueError('Diagnostic report must be under contained rebuild/validation')

CLEAN_DIAGNOSTIC = None

def fixture_value(value):
    # Called only on this script's disposable fixture, never on user data.
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): fixture_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [fixture_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):
        return fixture_value(value.value)
    return str(value)

def breadcrumb(event, **values):
    if CLEAN_DIAGNOSTIC is not None:
        CLEAN_DIAGNOSTIC['events'].append({
            'sequence': len(CLEAN_DIAGNOSTIC['events']) + 1,
            'event': event, **fixture_value(values),
        })

def guard_breadcrumb(stage, row, saved, fields, matched):
    differences = [
        {'field': key, 'actual': fixture_value(getattr(row, key, None)),
         'saved': fixture_value(getattr(saved, key, None))}
        for key in fields if getattr(row, key, None) != getattr(saved, key, None)
    ]
    breadcrumb('guard_return', stage=stage, row=type(row).__name__,
               row_id=getattr(row, 'id', None), matched=matched,
               differing_fields=differences)

def collect_identities():
    names = ['scripts/rebuild/test_plan_transactions.py',
             'backend/app/desktop_native/agent_transactions.py',
             'backend/app/agents/edit_planner.py', 'backend/app/agents/orchestrator.py',
             'backend/requirements.txt', 'backend/requirements-rebuild-storage.txt']
    sources = {}
    for name in names:
        path = REPO / name
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    dependencies = {}
    for name in ('SQLAlchemy', 'aiosqlite', 'greenlet', 'pydantic'):
        try:
            dependencies[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            dependencies[name] = None
    return {'source_sha256': sources, 'dependencies': dependencies,
            'python': sys.version, 'executable': sys.executable,
            'platform': platform.platform(), 'sqlite': sqlite3.sqlite_version,
            'fixture_schema': 'test_plan_transactions/clean-during/v1',
            'historical_ci_cause': 'UNKNOWN'}

def fresh_fixture_diagnostic():
    # Post-outcome read only, after normal dispose_db; does not replace assertions.
    database = CLEAN_DIAGNOSTIC.get('fixture_database')
    if not database or not Path(database).exists():
        return {'available': False}
    with closing(sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True)) as reader:
        reader.row_factory = sqlite3.Row
        plan = reader.execute(
            'SELECT plan_json, teacher_notes, is_approved, approved_at, estimated_duration '
            'FROM edit_plans WHERE video_id=?', (CLEAN_DIAGNOSTIC['video_id_hex'],)).fetchone()
        segment = reader.execute(
            'SELECT teacher_action, teacher_note, is_teacher_modified, action_reason '
            'FROM segments WHERE id=?', (CLEAN_DIAGNOSTIC['segment_id_hex'],)).fetchone()
    return {'available': True, 'plan': dict(plan) if plan else None,
            'teacher_segment': dict(segment) if segment else None,
            'observation_stage': 'after_child_outcome_and_normal_cleanup'}

def emit_clean_diagnostic():
    try:
        CLEAN_DIAGNOSTIC['final_fresh_fixture'] = fresh_fixture_diagnostic()
    except Exception as exc:
        CLEAN_DIAGNOSTIC['final_fresh_fixture'] = {'available': False,
            'read_error': {'type': type(exc).__name__, 'message': str(exc)}}
    record = json.dumps(CLEAN_DIAGNOSTIC, sort_keys=True)
    print('CLEAN_DURING_DIAGNOSTIC ' + record, flush=True)
    if DIAGNOSTIC_REPORT is not None:
        try:
            DIAGNOSTIC_REPORT.parent.mkdir(parents=True, exist_ok=True)
            DIAGNOSTIC_REPORT.write_text(record + '\n', encoding='utf-8')
        except Exception as exc:
            # Telemetry cannot mask the original test outcome or cleanup error.
            print('Diagnostic report write failed: ' + repr(exc), file=sys.stderr)

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
    if case=='clean-during':
        CLEAN_DIAGNOSTIC.update(fixture_database=str(paths.database), video_id_hex=vid.hex,
                                segment_id_hex=sid.hex, fixture_root=str(root))
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
    if case=='clean-during':breadcrumb('fixture_initial_commit_completed')
    calls=[];clean_calls=[];guard_differences=[]
    if case=='clean-during':
        CLEAN_DIAGNOSTIC.update(calls=calls, clean_calls=clean_calls, guard_differences=guard_differences)
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
        if case=='clean-during':breadcrumb('clean_callback_entered')
        unlocked('clean');clean_calls.append(kwargs['profile_id'])
        assert not hasattr(kwargs['plan'],'_sa_instance_state') and not hasattr(kwargs['segments'][0],'_sa_instance_state')
        if case=='clean-during':
            with closing(sqlite3.connect(paths.database,timeout=.15)) as writer:
                writer.execute("UPDATE edit_plans SET teacher_notes='concurrent teacher',is_approved=1,plan_json=?",('{"teacher_marker":"new plan"}',))
                writer.execute("UPDATE segments SET teacher_note='teacher decision',is_teacher_modified=1")
                writer.commit()
            breadcrumb('teacher_fixture_commit_completed', teacher_notes='concurrent teacher',
                       plan_json={'teacher_marker':'new plan'}, is_approved=True,
                       teacher_note='teacher decision', is_teacher_modified=True)
        kwargs['plan'].plan_json={'automatic_clean_marker':True};kwargs['plan'].estimated_duration=123
        kwargs['segments'][0].teacher_action=SegmentAction.CUT;kwargs['segments'][0].teacher_note='automatic suggestion'
        if case=='clean-during':breadcrumb('clean_callback_completed')
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
            if case in ('clean','clean-during'):
                # Distinct client defaults expose stale ORM postfetch state deterministically.
                updated_at_calls=0
                def distinct_updated_at(context):
                    nonlocal updated_at_calls
                    updated_at_calls+=1
                    return datetime(2026,1,1)+timedelta(microseconds=updated_at_calls)
                mocks.enter_context(patch.object(Segment.__table__.c.updated_at.onupdate,'arg',distinct_updated_at))
            if case=='clean-during':
                original_matches=planner._matches_snapshot
                def diagnosed_matches(row,saved,fields):
                    matched=original_matches(row,saved,fields)
                    guard_breadcrumb(sys._getframe(1).f_code.co_name, row,saved,fields,matched)
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
                        if case in ('clean','clean-during'):assert updated_at_calls>=16
                        if case=='guard-after-plan':
                            await teacher()
                            with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):await planner._read_guarded_native_plan(db,str(vid))
                        elif case=='clean-before':
                            await teacher()
                            with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):await pipeline._run_native_auto_clean(str(vid),db,clean)
                            assert clean_calls==[]
                        elif case=='clean-during':
                            previous_profile=sys.getprofile()
                            def clean_guard_profile(frame,event,arg):
                                # Observe the existing local post-clean predicate's return;
                                # never call it again or change its result/short circuiting.
                                if (event=='return' and frame.f_code.co_name=='matches'
                                        and frame.f_code.co_filename==pipeline.__file__):
                                    local=frame.f_locals
                                    guard_breadcrumb('post_clean_apply',local['row'],local['saved'],local['fields'],arg)
                                if previous_profile is not None:previous_profile(frame,event,arg)
                            sys.setprofile(clean_guard_profile)
                            try:
                                with unittest.TestCase().assertRaises(planner.StaleEditPlanningError):
                                    try:
                                        await pipeline._run_native_auto_clean(str(vid),db,clean)
                                    except planner.StaleEditPlanningError as exc:
                                        breadcrumb('stale_rejection', stage=(
                                            'post_callback' if 'clean_callback_completed' in
                                            [event['event'] for event in CLEAN_DIAGNOSTIC['events']]
                                            else 'callback_incomplete' if 'clean_callback_entered' in
                                            [event['event'] for event in CLEAN_DIAGNOSTIC['events']]
                                            else 'before_callback'), exception_type=type(exc).__name__, message=str(exc))
                                        raise
                            finally:sys.setprofile(previous_profile)
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
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(REPO),'--child',case,temp]+
                (['--diagnostic-report',str(DIAGNOSTIC_REPORT)] if case=='clean-during' and DIAGNOSTIC_REPORT else []),cwd=REPO,
                env=os.environ.copy(),capture_output=True,text=True,timeout=60)
            if case=='clean-during':
                print('CLEAN_DURING_PROCESS_EXIT '+json.dumps({'returncode':result.returncode}),flush=True)
                # Successful child output is normally captured by unittest; surface
                # its structured breadcrumbs in required CI as well as failures.
                for line in result.stdout.splitlines():
                    if line.startswith('CLEAN_DURING_DIAGNOSTIC '):print(line,flush=True)
                if DIAGNOSTIC_REPORT is not None and DIAGNOSTIC_REPORT.exists():
                    try:
                        report=json.loads(DIAGNOSTIC_REPORT.read_text(encoding='utf-8'))
                        report['observed_subprocess_returncode']=result.returncode
                        DIAGNOSTIC_REPORT.write_text(json.dumps(report,sort_keys=True)+'\n',encoding='utf-8')
                    except Exception as exc:
                        print('Diagnostic exit update failed: '+repr(exc),file=sys.stderr)
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
    if len(sys.argv)>1 and sys.argv[1]=='--child':
        if sys.argv[2]!='clean-during':asyncio.run(exercise(sys.argv[2],Path(sys.argv[3])))
        else:
            CLEAN_DIAGNOSTIC={'case':'clean-during','events':[], 'identities':collect_identities()}
            try:
                asyncio.run(exercise(sys.argv[2],Path(sys.argv[3])))
            except BaseException as exc:
                CLEAN_DIAGNOSTIC['outcome']={'status':'failure','exception_type':type(exc).__name__,
                    'message':str(exc), 'exception_exit_status':
                    (exc.code if isinstance(exc,SystemExit) and isinstance(exc.code,int) else 1)}
                raise
            else:CLEAN_DIAGNOSTIC['outcome']={'status':'success','exception':None,'exception_exit_status':0}
            finally:emit_clean_diagnostic()
    else:unittest.main(verbosity=2)
