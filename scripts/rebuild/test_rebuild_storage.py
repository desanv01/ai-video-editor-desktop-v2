"""Main-owned acceptance using real LanceDB and disposable SQLite files."""
import asyncio
from contextlib import closing
import hashlib
import math
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(sys.argv.pop(1)) if len(sys.argv)>1 and not sys.argv[1].startswith('-') else Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'backend'/'app'))
from desktop_native.vector_store import LanceVectorStore
from desktop_native.index_journal import INDEX_DDL
from desktop_native.sqlite_schema import preflight_native_schema, initialize_native_schema, MIGRATIONS
from desktop_native.sqlite_storage import backup_database, restore_database
from sqlalchemy import create_engine, MetaData, Table, Column, String

class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='aive-real-storage-')
        self.root=Path(self.temp.name); self.database=self.root/'engine.sqlite3'
        with closing(sqlite3.connect(self.database)) as db, db:
            for statement in INDEX_DDL: db.execute(statement)
        self.store=self.new_store();await self.store.ensure('selected-provider/model/3')
    def new_store(self):
        return LanceVectorStore(self.root/'vectors',database_path=self.database,collection='materials',dimensions=3)
    async def asyncTearDown(self):
        await self.store.close();self.temp.cleanup()
    async def replace(self,source,vectors,texts=None,kind='course_material'):
        texts=texts or [source+str(i) for i in range(len(vectors))]
        return await self.store.replace([{'text':s,'metadata':{'page_num':i+1,'filename':'notes.pdf'}} for i,s in enumerate(texts)],vectors,source,kind,'selected-provider/model/3')
    async def test_real_cosine_prefilter_threshold_payload_and_reopen(self):
        await self.replace('nearest-unwanted',[[1,0,0]])
        await self.replace("teacher's notes",[[0.8,0.6,0],[-1,0,0]],['lesson','opposite'])
        hits=await self.store.search([1,0,0],'selected-provider/model/3',source_id="teacher's notes",top_k=1)
        self.assertEqual(hits[0].payload['text'],'lesson');self.assertAlmostEqual(hits[0].score,0.8,places=6)
        self.assertEqual(hits[0].payload['page_num'],1)
        self.assertEqual(await self.store.search([1,0,0],'selected-provider/model/3',source_id="teacher's notes",score_threshold=0.81),[])
        all_hits=await self.store.search([1,0,0],'selected-provider/model/3',source_id="teacher's notes",score_threshold=-1)
        self.assertEqual(len(all_hits),2);self.assertAlmostEqual(all_hits[-1].score,-1,places=6)
        await self.store.close();self.store=self.new_store();await self.store.ensure('selected-provider/model/3')
        self.assertEqual((await self.store.stats('selected-provider/model/3'))['points_count'],3)
        await self.store.delete_by_source("teacher's notes",'selected-provider/model/3')
        self.assertEqual(await self.store.search([1,0,0],'selected-provider/model/3',source_id="teacher's notes"),[])
    async def test_replacement_removes_stale_rows_and_validates_before_mutation(self):
        await self.replace('lesson',[[1,0,0],[0,1,0]])
        await self.replace('lesson',[[0,0,1]],['updated'])
        self.assertEqual((await self.store.stats('selected-provider/model/3'))['points_count'],1)
        for invalid in [[0,0,0],[float('nan'),0,1],[1,2],[float('inf'),0,1]]:
            with self.assertRaises(ValueError):await self.replace('lesson',[invalid])
        self.assertEqual((await self.store.stats('selected-provider/model/3'))['points_count'],1)
        with self.assertRaisesRegex(RuntimeError,'configuration mismatch'):
            await self.store.check_configuration('another/model/3')
        await self.store.reset('another/model/3');await self.store.ensure('another/model/3')
        self.assertEqual((await self.store.stats('another/model/3'))['points_count'],0)
    async def test_interrupted_partial_generation_is_replayed_from_saved_vectors(self):
        await self.replace('lesson',[[1,0,0]],['old'])
        original=self.store._table
        class InterruptedTable:
            def __getattr__(self,name):return getattr(original,name)
            def merge_insert(self,key):
                builder=original.merge_insert(key)
                class InterruptedMerge:
                    def when_matched_update_all(self):builder.when_matched_update_all();return self
                    def when_not_matched_insert_all(self):builder.when_not_matched_insert_all();return self
                    def execute(self,rows):builder.execute(rows[:1]);raise RuntimeError('injected interruption after partial local index write')
                return InterruptedMerge()
        self.store._table=InterruptedTable()
        with self.assertRaisesRegex(RuntimeError,'injected interruption'):
            await self.replace('lesson',[[0,1,0],[0,0,1]],['new-one','new-two'])
        visible=self.store.journal.visibility('selected-provider/model/3')
        self.assertEqual(len(visible),1)
        self.assertEqual(original.count_rows("generation = '"+visible[0]['published_generation']+"'"),1)
        self.assertEqual(len(self.store.journal.pending()),1)
        await self.store.close();self.store=self.new_store();await self.store.ensure('selected-provider/model/3')
        self.assertEqual(self.store.journal.pending(),[])
        self.assertEqual((await self.store.stats('selected-provider/model/3'))['points_count'],2)
        hits=await self.store.search([0,1,0],'selected-provider/model/3',source_id='lesson')
        self.assertEqual({h.payload['text'] for h in hits},{'new-one','new-two'})

class SQLiteTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='aive-sqlite-main-');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_future_revision_rejected_without_schema_change(self):
        p=self.root/'future.sqlite3'
        with closing(sqlite3.connect(p)) as db, db:
            db.execute('CREATE TABLE desktop_schema_migrations(revision TEXT)');db.execute("INSERT INTO desktop_schema_migrations VALUES('999_future')")
        before=hashlib.sha256(p.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RuntimeError,'future'):preflight_native_schema(p)
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),before)
    def test_atomic_migration_rollback_and_known_legacy_columns(self):
        p=self.root/'legacy.sqlite3'
        with closing(sqlite3.connect(p)) as db, db:
            db.execute('CREATE TABLE videos(id TEXT PRIMARY KEY)');db.execute('CREATE TABLE project_assets(id TEXT PRIMARY KEY)')
        expected=preflight_native_schema(p);self.assertTrue(expected['legacy']);self.assertTrue(expected['upgrade'])
        metadata=MetaData();Table('videos',metadata,Column('id',String,primary_key=True));Table('project_assets',metadata,Column('id',String,primary_key=True))
        engine=create_engine('sqlite:///'+p.as_posix())
        with self.assertRaisesRegex(RuntimeError,'injected'):
            with engine.begin() as conn:
                conn.exec_driver_sql('BEGIN IMMEDIATE');initialize_native_schema(conn,metadata,expected);raise RuntimeError('injected upgrade interruption')
        self.assertEqual(preflight_native_schema(p)['applied'],[])
        with engine.begin() as conn:
            conn.exec_driver_sql('BEGIN IMMEDIATE');initialize_native_schema(conn,metadata,expected)
        self.assertEqual(preflight_native_schema(p)['applied'],[x[0] for x in MIGRATIONS])
        with engine.connect() as conn:self.assertIn('source_type',[row[1] for row in conn.exec_driver_sql('PRAGMA table_info(project_assets)')])
        engine.dispose()
    def test_online_backup_includes_wal_and_restore_preserves_current(self):
        p=self.root/'live.sqlite3';backup=self.root/'snapshot.sqlite3'
        live=sqlite3.connect(p);live.execute('PRAGMA journal_mode=WAL');live.execute('CREATE TABLE edits(value TEXT)');live.execute("INSERT INTO edits VALUES('teacher override')");live.commit()
        backup_database(p,backup)
        live.execute("UPDATE edits SET value='later edit'");live.commit();live.close()
        previous=restore_database(p,backup)
        with closing(sqlite3.connect(p)) as db, db:self.assertEqual(db.execute('SELECT value FROM edits').fetchone()[0],'teacher override')
        with closing(sqlite3.connect(previous)) as db, db:self.assertEqual(db.execute('SELECT value FROM edits').fetchone()[0],'later edit')

if __name__=='__main__':unittest.main(verbosity=2)
