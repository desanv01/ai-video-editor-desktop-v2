"""Main-owned runtime acceptance, isolated process and disposable profile per case."""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

REPO=Path(__file__).resolve().parents[2]

async def child(case, root):
    sys.path.insert(0,str(REPO/'backend'/'app'))
    # Resolve explicit paths before importing global Settings/database.
    from desktop_native.paths import NativeDesktopPaths
    paths=NativeDesktopPaths.from_environment(data_root=root,
        overrides={'ffmpeg_component':REPO/'fixtures'/'desktop-v2'/'native-tools'})
    os.environ.update(paths.settings_environment())
    os.environ['RUNTIME_PROFILE']='desktop-native'
    os.environ['EMBEDDING_DIMENSIONS']='3'
    import desktop_native.runtime as module
    runtime=module.NativeDesktopRuntime(paths,'runtime-main-test-token-123456789012345678','runtime-test-session',allow_tool_fixture=True)
    assert runtime.jobs is None and runtime.ffmpeg_probe is None
    if case=='future':
        with closing(sqlite3.connect(paths.database)) as db, db:
            db.execute('CREATE TABLE desktop_schema_migrations(revision TEXT)')
            db.execute("INSERT INTO desktop_schema_migrations VALUES ('999_future')")
        original=hashlib.sha256(paths.database.read_bytes()).hexdigest()
        try:
            await runtime.startup()
        except RuntimeError as exc:
            assert 'future' in str(exc)
        else:
            raise AssertionError('future database accepted')
        assert hashlib.sha256(paths.database.read_bytes()).hexdigest()==original
        assert runtime.jobs is None and not runtime.database_ready and not runtime.api_ready
        with closing(sqlite3.connect(paths.database)) as db:
            assert [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]==['desktop_schema_migrations']
        await runtime.shutdown()
    elif case=='startup-close':
        main_thread=threading.get_ident(); original_probe=module.discover_ffmpeg
        def probe(*args,**kwargs):
            assert threading.get_ident()!=main_thread
            return original_probe(*args,**kwargs)
        with patch.object(module,'discover_ffmpeg',probe):
            await runtime.startup()
        from rag.vector_store import rag_service
        assert runtime.vector_capability is rag_service.capability
        assert runtime.vector_capability.state=='available', runtime.vector_capability.detail
        assert runtime.database_ready and runtime.api_ready and runtime.jobs is not None
        assert runtime.ffmpeg_probe.ready
        with runtime.jobs._session() as db:
            assert db.execute('PRAGMA synchronous').fetchone()[0]==2
        runtime.vector_capability.state='unavailable'
        runtime.vector_capability.detail='injected local query failure'
        assert runtime.health_payload()['checks']['vectorStore']['detail']=='injected local query failure'
        await runtime.shutdown(); await runtime.shutdown()
        assert not runtime.api_ready and runtime.jobs is None
        assert rag_service.client._connection is None and rag_service.client._table is None
    elif case=='cancel-model-close':
        import desktop_native.model_manager as manager
        entered,release,finished=threading.Event(),threading.Event(),threading.Event()
        def stop():
            entered.set();assert release.wait(10);finished.set()
        close=AsyncMock();dispose=AsyncMock();runtime._rag_service=SimpleNamespace(close=close)
        with patch.object(manager,'shutdown_native_model_store',stop),patch.object(module,'dispose_db',dispose):
            owner=asyncio.create_task(runtime.shutdown())
            try:
                assert await asyncio.to_thread(entered.wait,5)
                owner.cancel();await asyncio.sleep(0)
            finally:release.set()
            try:await owner
            except asyncio.CancelledError:pass
            else:raise AssertionError('caller cancellation was lost')
            assert finished.is_set(), 'owned model shutdown must complete'
            assert close.await_count==1, 'cancelled model shutdown skipped LanceDB close'
            assert dispose.await_count==1, 'cancelled model shutdown skipped SQLite disposal'
            assert runtime._shutdown_complete, 'completed cleanup must remain idempotent'
            await runtime.shutdown();assert close.await_count==1 and dispose.await_count==1
    elif case=='failed-close':
        close=AsyncMock(side_effect=RuntimeError('injected close error'))
        dispose=AsyncMock()
        runtime._rag_service=SimpleNamespace(close=close)
        with patch.object(module,'dispose_db',dispose):
            try:
                await runtime.shutdown()
            except RuntimeError as exc:
                assert 'injected close error' in str(exc)
            else:
                raise AssertionError('close failure was ignored')
            assert dispose.await_count==1 and not runtime._shutdown_complete
            close.side_effect=None
            await runtime.shutdown(); await runtime.shutdown()
            assert dispose.await_count==2 and close.await_count==2
    print(json.dumps({'case':case,'status':'passed','scope':'source runtime, disposable profile; no live provider'}))

class RuntimeTests(unittest.TestCase):
    def run_case(self,case):
        output_root=REPO/'.test-output'/'runtime'
        output_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=case+'-',dir=output_root) as root:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child',case,root],
                cwd=REPO,env=os.environ.copy(),text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertIn('"status": "passed"',result.stdout)
    def test_cancelled_model_shutdown_still_closes_lance_and_sqlite(self):self.run_case('cancel-model-close')
    def test_future_revision_fails_before_job_schema_mutation(self):self.run_case('future')
    def test_actual_startup_capability_reference_and_repeated_close(self):self.run_case('startup-close')
    def test_database_disposal_when_lance_close_fails_and_retry(self):self.run_case('failed-close')

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':asyncio.run(child(sys.argv[2],Path(sys.argv[3])))
    else:unittest.main(verbosity=2)
