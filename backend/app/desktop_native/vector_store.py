"""Native exact cosine retrieval with SQLite-published LanceDB generations."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop_native.index_journal import IndexJournal

@dataclass
class VectorCapability:
    backend: str
    state: str
    detail: str
    remediation_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {'backend': self.backend, 'state': self.state, 'detail': self.detail,
                'remediationCodes': list(self.remediation_codes)}

@dataclass(frozen=True)
class LocalScoredPoint:
    id: str
    score: float
    payload: dict[str, Any]


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_vector(vector, dimensions: int) -> list[float]:
    if len(vector) != dimensions:
        raise ValueError(f'Embedding dimension mismatch: expected {dimensions}, got {len(vector)}; reindex required')
    result = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in result) or not any(result):
        raise ValueError('Embedding must contain finite values and have nonzero norm')
    # Lance stores float32: reject values that overflow or vanish at that boundary.
    try:
        stored = [struct.unpack('f', struct.pack('f', value))[0] for value in result]
    except (OverflowError, struct.error) as exc:
        raise ValueError('Embedding cannot be represented as float32') from exc
    if not all(math.isfinite(value) for value in stored) or not any(stored):
        raise ValueError('Embedding must have finite nonzero float32 norm')
    return result


class LanceVectorStore:
    def __init__(self, root: str | Path, *, database_path: str | Path, collection: str, dimensions: int):
        self.root = Path(root).resolve(strict=False)
        self.dimensions = int(dimensions)
        if self.dimensions <= 0:
            raise ValueError('Embedding dimensions must be positive')
        self.journal = IndexJournal(Path(database_path).resolve(strict=False), collection)
        self._table_name = 'aive_' + hashlib.sha256(collection.encode()).hexdigest()[:24]
        self._lock = asyncio.Lock()
        self._connection = None
        self._table = None
        self.capability = VectorCapability('lancedb', 'unavailable', 'LanceDB has not been opened/recovered', ('VECTOR_STORE_UNAVAILABLE',))

    async def _local(self, function, *args):
        # Cancellation must not release the adapter lock while a local mutation
        # continues in its executor thread. Journal recovery handles cancellation
        # between these bounded local steps.
        task = asyncio.create_task(asyncio.to_thread(function,*args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    def _failed(self, exc):
        self.capability.state = 'unavailable'
        self.capability.detail = f'LanceDB operation failed: {type(exc).__name__}: {exc}'
        self.capability.remediation_codes = ('VECTOR_STORE_UNAVAILABLE',)

    def _open(self):
        if self._table is not None:
            return
        import lancedb
        import pyarrow as pa
        self.root.mkdir(parents=True, exist_ok=True)
        self._connection = lancedb.connect(str(self.root))
        schema = pa.schema([
            pa.field('vector', pa.list_(pa.float32(), self.dimensions)),
            *[pa.field(name, pa.string()) for name in ('chunk_id','row_id','source_type','source_id','config','generation','payload_json')],
        ])
        if self._table_name not in self._connection.table_names() and self.journal.published_counts():
            raise RuntimeError('Published LanceDB table is missing; explicit recovery/reindex required')
        self._table = self._connection.create_table(self._table_name, schema=schema, exist_ok=True)
        if self._table.schema != schema:
            self._table = None
            if any(op['kind']=='reset' for op in self.journal.pending()):
                self._connection.drop_table(self._table_name)
                self._table = self._connection.create_table(self._table_name,schema=schema)
            else:
                raise RuntimeError('LanceDB schema/dimension mismatch: explicit reindex required')

    def _require_open(self):
        if self._table is None or self.capability.state != 'available':
            raise RuntimeError('LanceDB is unavailable; ensure_collection recovery is required')

    def _source_predicate(self, operation):
        return f"source_type = {sql_literal(operation['source_type'])} AND source_id = {sql_literal(operation['source_id'])}"

    def _replay(self):
        for operation in self.journal.pending():
            kind = operation['kind']
            if kind == 'replace':
                rows = self.journal.chunks(operation)
                if len(rows) != operation['expected_count']:
                    raise RuntimeError('Pending index snapshot is incomplete; refusing publication')
                for row in rows:
                    validate_vector(row['vector'], self.dimensions)
                if rows and operation['status'] == 'pending':
                    self._table.merge_insert('row_id').when_matched_update_all().when_not_matched_insert_all().execute(rows)
                predicate = self._source_predicate(operation)
                generation = sql_literal(operation['generation'])
                if self._table.count_rows(f'{predicate} AND generation = {generation}') != len(rows):
                    raise RuntimeError('LanceDB replacement incomplete; saved snapshots retained')
                if operation['status'] == 'pending':
                    self.journal.publish(operation)
                self._table.delete(f'{predicate} AND generation <> {generation}')
            elif kind == 'delete':
                self._table.delete(self._source_predicate(operation))
            elif kind == 'reset':
                self._table.delete('true')
            else:
                raise RuntimeError(f'Unknown index operation: {kind}')
            self.journal.finish(operation)

    def _verify_published(self):
        for source in self.journal.published_counts():
            predicate = self._source_predicate(source)
            generation = sql_literal(source['published_generation'])
            if self._table.count_rows(f'{predicate} AND generation = {generation}') != source['expected_count']:
                raise RuntimeError('Published LanceDB generation is missing/incomplete; explicit recovery/reindex required')

    async def ensure(self, config: str):
        async with self._lock:
            try:
                await self._local(self._open)
                # Recover deletes/reset even if the selected configuration changed.
                await self._local(self._replay)
                await self._local(self.journal.require_configuration, config)
                await self._local(self._verify_published)
                self.capability.state = 'available'
                self.capability.detail = 'LanceDB exact cosine index opened with durable SQLite generation visibility'
                self.capability.remediation_codes = ()
            except Exception as exc:
                self._failed(exc)
                raise

    async def check_configuration(self, config: str):
        async with self._lock:
            self._require_open()
            await self._local(self.journal.require_configuration, config)

    async def replace(self, chunks: list[dict], embeddings: list[list[float]], source_id: str, source_type: str, config: str):
        if len(chunks) != len(embeddings):
            raise ValueError('Embedding count does not match chunk count')
        vectors = [validate_vector(vector, self.dimensions) for vector in embeddings]
        payloads = []
        for index, chunk in enumerate(chunks):
            payload = {'text':chunk['text'], 'source_id':source_id, 'source_type':source_type, 'chunk_index':index}
            payload.update({key:value for key,value in chunk.get('metadata',{}).items() if value is not None})
            payloads.append(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False))
        generation = hashlib.sha256(json.dumps([config,payloads,vectors],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        rows = []
        for index, (payload, vector) in enumerate(zip(payloads,vectors)):
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL,json.dumps([source_type,source_id,index,config],separators=(',',':'))))
            rows.append(dict(chunk_id=chunk_id,row_id=str(uuid.uuid5(uuid.NAMESPACE_URL,chunk_id+':'+generation)),source_type=source_type,source_id=source_id,config=config,generation=generation,payload_json=payload,vector=vector))
        async with self._lock:
            self._require_open()
            try:
                await self._local(self._replay)
                await self._local(self.journal.require_configuration, config)
                await self._local(self.journal.replace,source_type,source_id,generation,config,rows)
                await self._local(self._replay)
            except Exception as exc:
                self._failed(exc)
                raise
        return len(rows)

    async def search(self, vector, config: str, *, source_type=None, source_id=None, top_k=5, score_threshold=0.0):
        vector = validate_vector(vector,self.dimensions)
        async with self._lock:
            self._require_open()
            try:
                await self._local(self.journal.require_configuration,config)
                visible = await self._local(self.journal.visibility,config)
                selected = [row for row in visible if (source_type is None or row['source_type']==source_type) and (source_id is None or row['source_id']==source_id)]
                if not selected or int(top_k)<=0:
                    return []
                visibility = ' OR '.join(f"(source_type = {sql_literal(row['source_type'])} AND source_id = {sql_literal(row['source_id'])} AND generation = {sql_literal(row['published_generation'])})" for row in selected)
                predicate = f'config = {sql_literal(config)} AND ({visibility})'
                def query():
                    return self._table.search(vector).distance_type('cosine').bypass_vector_index().where(predicate,prefilter=True).limit(int(top_k)).to_list()
                rows = await self._local(query)
                hits = []
                for row in rows:
                    score = 1.0-float(row['_distance'])
                    if score_threshold>0 and score<score_threshold:
                        continue
                    hits.append(LocalScoredPoint(row['chunk_id'],score,json.loads(row['payload_json'])))
                return hits
            except Exception as exc:
                self._failed(exc)
                raise

    async def stats(self, config: str):
        async with self._lock:
            self._require_open()
            await self._local(self.journal.require_configuration,config)
            count = await self._local(self.journal.count,config)
            return {'collection':self.journal.collection,'points_count':count,'vectors_count':count,'status':'green','backend':'lancedb','embedding_dimensions':self.dimensions}

    async def delete_by_source(self, source_id: str, config: str):
        async with self._lock:
            self._require_open()
            try:
                await self._local(self._replay)
                await self._local(self.journal.delete,source_id,config)
                await self._local(self._replay)
            except Exception as exc:
                self._failed(exc)
                raise

    async def reset(self, config: str):
        async with self._lock:
            try:
                await self._local(self.journal.reset,config)
                await self._local(self._open)
                await self._local(self._replay)
                self.capability.state = 'available'
                self.capability.detail = 'LanceDB collection reset and journal completed'
                self.capability.remediation_codes = ()
            except Exception as exc:
                self._failed(exc)
                raise

    async def close(self):
        async with self._lock:
            def close():
                for resource in (self._table,self._connection):
                    method = getattr(resource,'close',None)
                    if method:
                        method()
            await self._local(close)
            self._table = self._connection = None
            self.capability.state = 'unavailable'
            self.capability.detail = 'LanceDB closed'


def create_local_vector_client(root: str | Path, *, dimensions: int, database_path: str | Path, collection: str):
    client = LanceVectorStore(root,database_path=database_path,collection=collection,dimensions=dimensions)
    return client, client.capability
