"""Persistent embedded vector-store adapters for the native profile.

Qdrant local/path mode is preferred when the installed qdrant-client supports
it.  The SQLite cosine fallback is deliberately capability-labelled as
degraded and reports that it is not an external-Qdrant equivalent.
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable


@dataclass(frozen=True)
class VectorCapability:
    backend: str
    state: str
    detail: str
    remediation_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "state": self.state,
            "detail": self.detail,
            "remediationCodes": list(self.remediation_codes),
        }


@dataclass(frozen=True)
class LocalScoredPoint:
    id: str
    score: float
    payload: dict[str, Any]


def _filter_pairs(selector: Any) -> list[tuple[str, Any]]:
    filter_value = getattr(selector, "filter", selector)
    conditions = getattr(filter_value, "must", None) or []
    pairs: list[tuple[str, Any]] = []
    for condition in conditions:
        key = getattr(condition, "key", None)
        match = getattr(condition, "match", None)
        value = getattr(match, "value", None)
        if key is not None:
            pairs.append((str(key), value))
    return pairs


class AsyncLocalQdrantAdapter:
    """Async facade over qdrant-client's persistent local mode."""

    def __init__(self, client: Any):
        self._client = client

    async def get_collections(self):
        return await asyncio.to_thread(self._client.get_collections)

    async def create_collection(self, **kwargs):
        return await asyncio.to_thread(lambda: self._client.create_collection(**kwargs))

    async def get_collection(self, collection_name: str):
        return await asyncio.to_thread(lambda: self._client.get_collection(collection_name))

    async def delete_collection(self, collection_name: str):
        return await asyncio.to_thread(lambda: self._client.delete_collection(collection_name))

    async def upsert(self, **kwargs):
        return await asyncio.to_thread(lambda: self._client.upsert(**kwargs))

    async def search(self, **kwargs):
        if hasattr(self._client, "search"):
            return await asyncio.to_thread(lambda: self._client.search(**kwargs))
        query = kwargs.pop("query_vector")
        return await asyncio.to_thread(
            lambda: self._client.query_points(query=query, **kwargs).points
        )

    async def delete(self, **kwargs):
        return await asyncio.to_thread(lambda: self._client.delete(**kwargs))


class SQLiteVectorClient:
    """Small persistent cosine-search fallback with an explicit capability."""

    def __init__(self, root: Path, dimensions: int):
        self.root = root
        self.database_path = root / "vectors.sqlite3"
        self.dimensions = dimensions
        self.root.mkdir(parents=True, exist_ok=True)
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_collections (
                    name TEXT PRIMARY KEY,
                    dimensions INTEGER NOT NULL,
                    distance TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vector_points (
                    collection TEXT NOT NULL REFERENCES vector_collections(name) ON DELETE CASCADE,
                    point_id TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(collection, point_id)
                );
                CREATE INDEX IF NOT EXISTS ix_vector_points_collection
                    ON vector_points(collection);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def _session(self):  # type: ignore[no-untyped-def]
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    async def get_collections(self):
        def read():
            with self._session() as connection:
                rows = connection.execute(
                    "SELECT name FROM vector_collections ORDER BY name"
                ).fetchall()
            return SimpleNamespace(collections=[SimpleNamespace(name=row["name"]) for row in rows])

        return await asyncio.to_thread(read)

    async def create_collection(self, *, collection_name: str, vectors_config: Any, **_kwargs):
        dimensions = int(getattr(vectors_config, "size", self.dimensions))
        distance = str(getattr(vectors_config, "distance", "Cosine"))

        def create():
            with self._session() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO vector_collections (name, dimensions, distance) "
                    "VALUES (?, ?, ?)",
                    (collection_name, dimensions, distance),
                )
                connection.commit()

        await asyncio.to_thread(create)
        return True

    async def get_collection(self, collection_name: str):
        def read():
            with self._session() as connection:
                collection = connection.execute(
                    "SELECT dimensions FROM vector_collections WHERE name = ?",
                    (collection_name,),
                ).fetchone()
                if collection is None:
                    raise KeyError(collection_name)
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM vector_points WHERE collection = ?",
                    (collection_name,),
                ).fetchone()["count"]
            return SimpleNamespace(
                points_count=count,
                vectors_count=count,
                status=SimpleNamespace(value="green"),
            )

        return await asyncio.to_thread(read)

    async def delete_collection(self, collection_name: str):
        def delete():
            with self._session() as connection:
                connection.execute("DELETE FROM vector_collections WHERE name = ?", (collection_name,))
                connection.commit()

        await asyncio.to_thread(delete)
        return True

    async def upsert(self, *, collection_name: str, points: Iterable[Any], **_kwargs):
        point_rows = []
        for point in points:
            point_id = str(getattr(point, "id", ""))
            vector = list(getattr(point, "vector", []) or [])
            payload = dict(getattr(point, "payload", {}) or {})
            point_rows.append((collection_name, point_id, json.dumps(vector), json.dumps(payload)))

        def write():
            with self._session() as connection:
                connection.executemany(
                    "INSERT OR REPLACE INTO vector_points "
                    "(collection, point_id, vector_json, payload_json) VALUES (?, ?, ?, ?)",
                    point_rows,
                )
                connection.commit()

        await asyncio.to_thread(write)
        return True

    async def search(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        query_filter: Any = None,
        limit: int = 5,
        score_threshold: float | None = None,
        **_kwargs,
    ):
        pairs = _filter_pairs(query_filter)

        def read():
            with self._session() as connection:
                rows = connection.execute(
                    "SELECT point_id, vector_json, payload_json FROM vector_points "
                    "WHERE collection = ?",
                    (collection_name,),
                ).fetchall()
            scored: list[LocalScoredPoint] = []
            for row in rows:
                payload = json.loads(row["payload_json"] or "{}")
                if any(payload.get(key) != value for key, value in pairs):
                    continue
                vector = json.loads(row["vector_json"] or "[]")
                score = _cosine_similarity(query_vector, vector)
                if score_threshold is not None and score < score_threshold:
                    continue
                scored.append(LocalScoredPoint(row["point_id"], score, payload))
            scored.sort(key=lambda item: item.score, reverse=True)
            return scored[: max(1, min(int(limit), 500))]

        return await asyncio.to_thread(read)

    async def delete(self, *, collection_name: str, points_selector: Any = None, **_kwargs):
        pairs = _filter_pairs(points_selector)

        def delete():
            with self._session() as connection:
                rows = connection.execute(
                    "SELECT point_id, payload_json FROM vector_points WHERE collection = ?",
                    (collection_name,),
                ).fetchall()
                ids = [
                    row["point_id"]
                    for row in rows
                    if all(json.loads(row["payload_json"] or "{}").get(key) == value for key, value in pairs)
                ]
                connection.executemany(
                    "DELETE FROM vector_points WHERE collection = ? AND point_id = ?",
                    [(collection_name, point_id) for point_id in ids],
                )
                connection.commit()

        await asyncio.to_thread(delete)
        return True


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def create_local_vector_client(
    root: str | Path,
    *,
    dimensions: int,
) -> tuple[Any, VectorCapability]:
    path = Path(root).resolve(strict=False)
    path.mkdir(parents=True, exist_ok=True)
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(path=str(path))
        # Force local-mode initialization now; no host/port is ever passed.
        client.get_collections()
        return (
            AsyncLocalQdrantAdapter(client),
            VectorCapability(
                backend="qdrant-local",
                state="available",
                detail=f"Persistent Qdrant local/path mode at {path}; no external server configured.",
            ),
        )
    except Exception as exc:  # pragma: no cover - depends on installed qdrant stack
        fallback = SQLiteVectorClient(path, dimensions)
        return (
            fallback,
            VectorCapability(
                backend="sqlite-cosine-fallback",
                state="degraded",
                detail=(
                    "Qdrant local/path mode was unavailable; using the explicit SQLite cosine "
                    f"fallback at {fallback.database_path}. This is not an external-Qdrant equivalent. "
                    f"Probe detail: {exc.__class__.__name__}: {exc}"
                ),
                remediation_codes=("VECTOR_STORE_UNAVAILABLE",),
            ),
        )
