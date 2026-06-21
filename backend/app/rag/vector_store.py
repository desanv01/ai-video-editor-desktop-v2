"""
RAG Vector Store Service — manages the Qdrant knowledge base.

Phase C: Complete RAG pipeline.

Handles:
  - Collection lifecycle (create, stats, reset)
  - Embedding with batching and rate limiting (OpenAI limit: 2048 per request)
  - Course material ingestion (page-aware chunking from PDF/PPTX/DOCX)
  - Transcript ingestion (time-aligned + speaker-aware chunking)
  - Semantic search with score threshold
  - Source-level CRUD (add/delete by source)
"""

import uuid
import asyncio
import logging
from typing import List, Optional, Dict, Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    models as qmodels,
)
from services.llm import llm_service
from config import settings

logger = logging.getLogger(__name__)

# OpenAI embedding API limits
EMBED_BATCH_SIZE = 512       # texts per API call (safe under 2048 limit)
EMBED_RATE_DELAY = 0.1       # seconds between batches to avoid rate limits
UPSERT_BATCH_SIZE = 100      # points per Qdrant upsert call


class RAGService:
    """Manages the Qdrant vector knowledge base for course materials and transcripts."""

    def __init__(self):
        self.client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
        self.collection_name = settings.QDRANT_COLLECTION
        self.embedding_dim = settings.EMBEDDING_DIMENSIONS

    # ═══════════════════════════════════════════
    #  COLLECTION LIFECYCLE
    # ═══════════════════════════════════════════

    async def ensure_collection(self):
        """Create the collection if it doesn't exist."""
        try:
            collections = await self.client.get_collections()
            existing = [c.name for c in collections.collections]

            if self.collection_name not in existing:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")
            else:
                logger.info(f"Qdrant collection exists: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to ensure Qdrant collection: {e}")
            raise

    async def get_collection_stats(self) -> dict:
        """Get collection statistics (point count, segment count, etc.)."""
        try:
            info = await self.client.get_collection(self.collection_name)
            return {
                "collection": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value if info.status else "unknown",
                "embedding_dimensions": self.embedding_dim,
            }
        except Exception as e:
            return {"collection": self.collection_name, "error": str(e)}

    async def reset_collection(self):
        """Delete and recreate the collection (for testing)."""
        try:
            await self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")
        except Exception:
            pass
        await self.ensure_collection()

    # ═══════════════════════════════════════════
    #  EMBEDDING (batched + rate-limited)
    # ═══════════════════════════════════════════

    async def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts with automatic batching.

        OpenAI's embedding API allows up to 2048 texts per call,
        but we use smaller batches (512) for reliability + rate limiting.
        """
        if not texts:
            return []

        all_embeddings = []

        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i:i + EMBED_BATCH_SIZE]
            try:
                embeddings = await llm_service.embed(batch)
                all_embeddings.extend(embeddings)
            except Exception as e:
                logger.error(f"Embedding batch {i//EMBED_BATCH_SIZE + 1} failed: {e}")
                # Retry once after a short delay
                await asyncio.sleep(2.0)
                try:
                    embeddings = await llm_service.embed(batch)
                    all_embeddings.extend(embeddings)
                except Exception as e2:
                    logger.error(f"Embedding retry failed: {e2}")
                    raise

            # Rate limiting between batches
            if i + EMBED_BATCH_SIZE < len(texts):
                await asyncio.sleep(EMBED_RATE_DELAY)

        return all_embeddings

    # ═══════════════════════════════════════════
    #  INGEST: Course Materials
    # ═══════════════════════════════════════════

    async def ingest_course_material(
        self,
        source_id: str,
        filename: str,
        pages: List[dict],
        chunk_size: int = 300,
        chunk_overlap: int = 50,
    ) -> int:
        """
        Ingest extracted course material into the vector store.

        Uses page-aware chunking: each chunk knows which page it came from.
        This lets Agent 2 say "this concept is on page 5 of the lecture notes."

        Args:
            source_id: UUID of the CourseMaterial record
            filename: Original filename (for metadata)
            pages: [{"page_num": 1, "text": "..."}, ...]
            chunk_size: Approximate tokens per chunk
            chunk_overlap: Overlap between chunks in tokens

        Returns:
            Number of chunks stored
        """
        chunks = self._chunk_pages(pages, filename, chunk_size, chunk_overlap)

        if not chunks:
            logger.warning(f"No chunks generated for {filename}")
            return 0

        await self._store_chunks(chunks, source_id, source_type="course_material")

        logger.info(f"Ingested {len(chunks)} chunks from {filename} into Qdrant")
        return len(chunks)

    def _chunk_pages(
        self,
        pages: List[dict],
        filename: str,
        chunk_size: int = 300,
        chunk_overlap: int = 50,
    ) -> List[dict]:
        """
        Chunk extracted pages into overlapping text segments.
        Preserves page boundaries when possible — never splits mid-sentence across pages.
        """
        words_per_chunk = int(chunk_size * 0.75)
        overlap_words = int(chunk_overlap * 0.75)
        chunks = []

        for page in pages:
            page_num = page.get("page_num", 0)
            text = page.get("text", "").strip()
            if not text:
                continue

            words = text.split()

            # If the page fits in one chunk, keep it as-is
            if len(words) <= words_per_chunk:
                chunks.append({
                    "text": text,
                    "metadata": {
                        "page_num": page_num,
                        "filename": filename,
                    },
                })
                continue

            # Split long pages into overlapping chunks
            start = 0
            while start < len(words):
                end = min(start + words_per_chunk, len(words))
                chunk_text = " ".join(words[start:end])
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "page_num": page_num,
                        "filename": filename,
                        "chunk_part": start // (words_per_chunk - overlap_words) + 1,
                    },
                })
                if end >= len(words):
                    break
                start += words_per_chunk - overlap_words

        return chunks

    # ═══════════════════════════════════════════
    #  INGEST: Transcript
    # ═══════════════════════════════════════════

    async def ingest_transcript(
        self,
        source_id: str,
        segments: List[dict],
        target_duration: float = 60.0,
    ) -> int:
        """
        Ingest transcript segments into the vector store.

        Uses time-aligned + speaker-aware chunking:
        - Groups segments into ~60-second windows
        - Preserves speaker labels so Agent 2 knows who said what
        - Each chunk has start_time/end_time for timeline alignment

        Args:
            source_id: UUID of the video (used as source_id)
            segments: [{"text": "...", "start": 0.0, "end": 30.0, "speaker": "S1"}, ...]
            target_duration: Target chunk duration in seconds

        Returns:
            Number of chunks stored
        """
        chunks = self.chunk_transcript_segments(segments, target_duration)

        if not chunks:
            return 0

        await self._store_chunks(chunks, source_id, source_type="transcript")

        logger.info(f"Ingested {len(chunks)} transcript chunks into Qdrant")
        return len(chunks)

    @staticmethod
    def chunk_transcript_segments(
        segments: List[dict],
        target_duration: float = 60.0,
    ) -> List[dict]:
        """
        Chunk transcript segments into ~60-second groups.
        Preserves time alignment and speaker labels.

        Tries to break at speaker transitions when possible
        (more natural boundaries than arbitrary time cuts).
        """
        if not segments:
            return []

        chunks = []
        current_texts = []
        current_speakers = set()
        current_start = segments[0].get("start", 0)
        current_duration = 0.0

        for i, seg in enumerate(segments):
            seg_text = seg.get("text", "").strip()
            if not seg_text:
                continue

            seg_duration = seg.get("end", 0) - seg.get("start", 0)
            seg_speaker = seg.get("speaker")

            # Check if we should break here
            should_break = current_duration >= target_duration

            # Prefer breaking at speaker transitions (more natural)
            if should_break and seg_speaker and seg_speaker not in current_speakers:
                should_break = True
            elif current_duration >= target_duration * 1.3:
                # Hard break if we're >30% over target
                should_break = True
            elif current_duration < target_duration:
                should_break = False

            if should_break and current_texts:
                # Emit chunk
                speaker_label = ", ".join(sorted(current_speakers)) if current_speakers else None
                chunks.append({
                    "text": " ".join(current_texts),
                    "metadata": {
                        "start_time": current_start,
                        "end_time": seg.get("start", current_start + current_duration),
                        "duration": current_duration,
                        "speakers": speaker_label,
                        "segment_count": len(current_texts),
                    },
                })
                current_texts = []
                current_speakers = set()
                current_start = seg.get("start", 0)
                current_duration = 0.0

            # Add segment to current chunk
            if seg_speaker:
                prefix = f"[{seg_speaker}] "
            else:
                prefix = ""
            current_texts.append(f"{prefix}{seg_text}")
            if seg_speaker:
                current_speakers.add(seg_speaker)
            current_duration += seg_duration

        # Don't forget the last chunk
        if current_texts:
            speaker_label = ", ".join(sorted(current_speakers)) if current_speakers else None
            chunks.append({
                "text": " ".join(current_texts),
                "metadata": {
                    "start_time": current_start,
                    "end_time": segments[-1].get("end", current_start + current_duration),
                    "duration": current_duration,
                    "speakers": speaker_label,
                    "segment_count": len(current_texts),
                },
            })

        return chunks

    # ═══════════════════════════════════════════
    #  STORAGE (shared by both ingest paths)
    # ═══════════════════════════════════════════

    async def add_chunks(
        self,
        chunks: List[dict],
        source_id: str,
        source_type: str,
    ) -> int:
        """Public wrapper to store arbitrary chunked text in Qdrant for semantic search.

        Args:
            chunks: List of dicts with ``text`` and optional ``metadata`` keys.
            source_id: Identifier for the source document (e.g. ``"<video_id>_slides"``).
            source_type: Category label used as a search filter (e.g. ``"slide_page"``).

        Returns:
            Number of chunks stored.
        """
        await self._store_chunks(chunks, source_id, source_type)
        return len(chunks)

    async def _store_chunks(
        self,
        chunks: List[dict],
        source_id: str,
        source_type: str,
    ):
        """Embed chunks and store them in Qdrant with metadata."""
        if not chunks:
            return

        # Extract texts for embedding
        texts = [c["text"] for c in chunks]

        # Batch embed
        logger.info(f"Embedding {len(texts)} chunks...")
        embeddings = await self._embed_texts(texts)

        # Build Qdrant points
        points = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            payload = {
                "text": chunk["text"],
                "source_id": source_id,
                "source_type": source_type,
                "chunk_index": i,
            }
            # Merge metadata
            for k, v in chunk.get("metadata", {}).items():
                if v is not None:
                    payload[k] = v

            points.append(PointStruct(
                id=point_id,
                vector=embedding,
                payload=payload,
            ))

        # Upsert in batches
        for i in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[i:i + UPSERT_BATCH_SIZE]
            await self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
            )

        logger.info(f"Stored {len(points)} points in Qdrant (source={source_type})")

    # ═══════════════════════════════════════════
    #  SEARCH
    # ═══════════════════════════════════════════

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        score_threshold: float = 0.0,
    ) -> List[dict]:
        """
        Search the knowledge base for content relevant to the query.

        Args:
            query: The search query text
            top_k: Maximum number of results
            source_type: Filter by "course_material" or "transcript"
            source_id: Filter by specific source document ID
            score_threshold: Minimum similarity score (0.0 = no threshold)

        Returns:
            List of matching chunks with scores and metadata
        """
        query_embedding = await llm_service.embed_single(query)

        # Build filter
        must_conditions = []
        if source_type:
            must_conditions.append(
                FieldCondition(key="source_type", match=MatchValue(value=source_type))
            )
        if source_id:
            must_conditions.append(
                FieldCondition(key="source_id", match=MatchValue(value=source_id))
            )

        search_filter = Filter(must=must_conditions) if must_conditions else None

        results = await self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            query_filter=search_filter,
            limit=top_k,
            score_threshold=score_threshold if score_threshold > 0 else None,
        )

        return [
            {
                "text": hit.payload.get("text", ""),
                "score": round(hit.score, 4),
                "source_id": hit.payload.get("source_id"),
                "source_type": hit.payload.get("source_type"),
                "chunk_index": hit.payload.get("chunk_index"),
                "metadata": {
                    k: v for k, v in hit.payload.items()
                    if k not in ("text", "source_id", "source_type", "chunk_index")
                },
            }
            for hit in results
        ]

    # ═══════════════════════════════════════════
    #  DELETE
    # ═══════════════════════════════════════════

    async def delete_by_source(self, source_id: str):
        """Delete all chunks belonging to a specific source document."""
        try:
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="source_id",
                                match=MatchValue(value=source_id),
                            )
                        ]
                    )
                ),
            )
            logger.info(f"Deleted chunks for source_id={source_id}")
        except Exception as e:
            logger.error(f"Failed to delete chunks for source_id={source_id}: {e}")
            raise

    # ═══════════════════════════════════════════
    #  LEGACY COMPAT (used by old code paths)
    # ═══════════════════════════════════════════

    async def add_chunks(
        self,
        chunks: List[dict],
        source_id: str,
        source_type: str = "course_material",
    ):
        """Legacy method — wraps _store_chunks for backward compatibility."""
        await self._store_chunks(chunks, source_id, source_type)

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = 300,
        overlap: int = 50,
    ) -> List[dict]:
        """Legacy method — simple word-based chunking."""
        words = text.split()
        words_per_chunk = int(chunk_size * 0.75)
        overlap_words = int(overlap * 0.75)

        chunks = []
        start = 0
        while start < len(words):
            end = min(start + words_per_chunk, len(words))
            chunk_text = " ".join(words[start:end])
            chunks.append({
                "text": chunk_text,
                "metadata": {"word_start": start, "word_end": end},
            })
            if end >= len(words):
                break
            start += words_per_chunk - overlap_words

        return chunks


# Singleton
rag_service = RAGService()
