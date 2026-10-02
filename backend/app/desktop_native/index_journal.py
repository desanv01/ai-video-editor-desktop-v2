"""Durable authoritative snapshots for the native LanceDB index."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

INDEX_DDL = (
    "CREATE TABLE IF NOT EXISTS desktop_index_sources (collection TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL, config TEXT NOT NULL, published_generation TEXT, tombstone INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(collection,source_type,source_id))",
    "CREATE TABLE IF NOT EXISTS desktop_index_chunks (collection TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL, generation TEXT NOT NULL, chunk_id TEXT NOT NULL, row_id TEXT NOT NULL, config TEXT NOT NULL, payload_json TEXT NOT NULL, vector_json TEXT NOT NULL, PRIMARY KEY(collection,row_id), FOREIGN KEY(collection,source_type,source_id) REFERENCES desktop_index_sources(collection,source_type,source_id) ON DELETE CASCADE)",
    "CREATE TABLE IF NOT EXISTS desktop_index_operations (operation_id TEXT PRIMARY KEY, collection TEXT NOT NULL, kind TEXT NOT NULL, source_type TEXT, source_id TEXT, generation TEXT, config TEXT NOT NULL, expected_count INTEGER NOT NULL DEFAULT 0, cleanup_pending INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL CHECK(status IN ('pending','complete')))",
    "CREATE INDEX IF NOT EXISTS ix_desktop_index_operations_pending ON desktop_index_operations(collection,status)",
)

class IndexJournal:
    def __init__(self, database_path: str | Path, collection: str):
        self.path = Path(database_path)
        self.collection = collection

    @contextmanager
    def session(self):
        # Never create a second database if native initialization was skipped.
        connection = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=30000')
            with connection:
                yield connection
        finally:
            connection.close()

    def require_configuration(self, config: str):
        with self.session() as db:
            rows = db.execute("SELECT DISTINCT config FROM desktop_index_sources WHERE collection=? UNION SELECT DISTINCT config FROM desktop_index_operations WHERE collection=? AND status='pending'", (self.collection, self.collection)).fetchall()
            if any(row[0] != config for row in rows):
                raise RuntimeError('Embedding configuration mismatch: explicit reset/reindex required')

    def replace(self, source_type: str, source_id: str, generation: str, config: str, rows: list[dict]):
        operation = json.dumps([self.collection, 'replace', source_type, source_id, generation], separators=(',', ':'))
        with self.session() as db:
            db.execute('INSERT INTO desktop_index_sources(collection,source_type,source_id,config) VALUES(?,?,?,?) ON CONFLICT(collection,source_type,source_id) DO NOTHING', (self.collection,source_type,source_id,config))
            db.executemany('INSERT OR REPLACE INTO desktop_index_chunks(collection,source_type,source_id,generation,chunk_id,row_id,config,payload_json,vector_json) VALUES(?,?,?,?,?,?,?,?,?)', [(self.collection,source_type,source_id,generation,r['chunk_id'],r['row_id'],config,r['payload_json'],json.dumps(r['vector'],allow_nan=False)) for r in rows])
            db.execute("INSERT INTO desktop_index_operations(operation_id,collection,kind,source_type,source_id,generation,config,expected_count,status) VALUES(?,?,'replace',?,?,?,?,?, 'pending') ON CONFLICT(operation_id) DO UPDATE SET status='pending',cleanup_pending=0", (operation,self.collection,source_type,source_id,generation,config,len(rows)))
        return operation

    def pending(self):
        with self.session() as db:
            return [dict(r) for r in db.execute("SELECT * FROM desktop_index_operations WHERE collection=? AND (status='pending' OR cleanup_pending=1) ORDER BY rowid", (self.collection,))]

    def chunks(self, operation: dict):
        with self.session() as db:
            rows = db.execute('SELECT * FROM desktop_index_chunks WHERE collection=? AND source_type=? AND source_id=? AND generation=? ORDER BY row_id', (self.collection,operation['source_type'],operation['source_id'],operation['generation'])).fetchall()
            return [dict(chunk_id=r['chunk_id'],row_id=r['row_id'],source_type=r['source_type'],source_id=r['source_id'],generation=r['generation'],config=r['config'],payload_json=r['payload_json'],vector=json.loads(r['vector_json'])) for r in rows]

    def publish(self, operation: dict):
        with self.session() as db:
            db.execute('UPDATE desktop_index_sources SET published_generation=?, tombstone=0 WHERE collection=? AND source_type=? AND source_id=?', (operation['generation'],self.collection,operation['source_type'],operation['source_id']))
            db.execute("UPDATE desktop_index_operations SET status='complete',cleanup_pending=1 WHERE operation_id=?", (operation['operation_id'],))

    def finish(self, operation: dict):
        with self.session() as db:
            if operation['kind'] == 'replace':
                db.execute('DELETE FROM desktop_index_chunks WHERE collection=? AND source_type=? AND source_id=? AND generation<>?', (self.collection,operation['source_type'],operation['source_id'],operation['generation']))
            elif operation['kind'] == 'delete':
                db.execute('DELETE FROM desktop_index_sources WHERE collection=? AND source_type=? AND source_id=?', (self.collection,operation['source_type'],operation['source_id']))
            elif operation['kind'] == 'reset':
                db.execute('DELETE FROM desktop_index_sources WHERE collection=?', (self.collection,))
            db.execute("UPDATE desktop_index_operations SET status='complete',cleanup_pending=0 WHERE operation_id=?", (operation['operation_id'],))

    def delete(self, source_id: str, config: str):
        with self.session() as db:
            sources = db.execute('SELECT source_type FROM desktop_index_sources WHERE collection=? AND source_id=?', (self.collection,source_id)).fetchall()
            for source in sources:
                operation = json.dumps([self.collection,'delete',source[0],source_id])
                db.execute('UPDATE desktop_index_sources SET tombstone=1,published_generation=NULL WHERE collection=? AND source_type=? AND source_id=?', (self.collection,source[0],source_id))
                db.execute("INSERT INTO desktop_index_operations(operation_id,collection,kind,source_type,source_id,config,status) VALUES(?,?,'delete',?,?,?,'pending') ON CONFLICT(operation_id) DO UPDATE SET status='pending',cleanup_pending=0", (operation,self.collection,source[0],source_id,config))

    def reset(self, config: str):
        with self.session() as db:
            db.execute('UPDATE desktop_index_sources SET tombstone=1,published_generation=NULL WHERE collection=?', (self.collection,))
            db.execute("UPDATE desktop_index_operations SET status='complete',cleanup_pending=0 WHERE collection=? AND (status='pending' OR cleanup_pending=1)", (self.collection,))
            operation = json.dumps([self.collection,'reset'])
            db.execute("INSERT INTO desktop_index_operations(operation_id,collection,kind,config,status) VALUES(?,?,'reset',?,'pending') ON CONFLICT(operation_id) DO UPDATE SET config=excluded.config,status='pending',cleanup_pending=0", (operation,self.collection,config))

    def visibility(self, config: str):
        with self.session() as db:
            return [dict(r) for r in db.execute('SELECT source_type,source_id,published_generation FROM desktop_index_sources WHERE collection=? AND config=? AND tombstone=0 AND published_generation IS NOT NULL', (self.collection,config))]

    def published_counts(self):
        with self.session() as db:
            return [dict(row) for row in db.execute('SELECT s.source_type,s.source_id,s.published_generation,COUNT(c.row_id) AS expected_count FROM desktop_index_sources s LEFT JOIN desktop_index_chunks c ON c.collection=s.collection AND c.source_type=s.source_type AND c.source_id=s.source_id AND c.generation=s.published_generation WHERE s.collection=? AND s.tombstone=0 AND s.published_generation IS NOT NULL GROUP BY s.source_type,s.source_id,s.published_generation', (self.collection,))]

    def count(self, config: str):
        with self.session() as db:
            return db.execute('SELECT COUNT(*) FROM desktop_index_chunks c JOIN desktop_index_sources s ON c.collection=s.collection AND c.source_type=s.source_type AND c.source_id=s.source_id AND c.generation=s.published_generation WHERE s.collection=? AND s.config=? AND s.tombstone=0', (self.collection,config)).fetchone()[0]
