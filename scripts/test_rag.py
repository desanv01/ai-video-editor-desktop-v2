#!/usr/bin/env python3
"""
Phase C Test Script — RAG Pipeline End-to-End Test
====================================================

Tests the full RAG pipeline:
  1. Text extraction (PDF/PPTX/DOCX/TXT)
  2. Page-aware chunking
  3. Embedding (OpenAI API)
  4. Storage in Qdrant
  5. Semantic search and retrieval

Usage:
    # Test with a course material file:
    python scripts/test_rag.py --file /path/to/lecture_notes.pdf

    # Test with a search query after ingestion:
    python scripts/test_rag.py --file notes.pdf --query "What is quicksort?"

    # Test search only (assumes materials already ingested):
    python scripts/test_rag.py --search "binary search algorithm"

    # Show collection stats:
    python scripts/test_rag.py --stats

    # Reset collection:
    python scripts/test_rag.py --reset

Environment:
    Requires OPENAI_API_KEY in .env (for embeddings).
    Requires Qdrant running (docker-compose up qdrant).
"""

import asyncio
import argparse
import os
import sys
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def main():
    parser = argparse.ArgumentParser(description="Test RAG pipeline")
    parser.add_argument("--file", type=str, help="Path to document to ingest (PDF/PPTX/DOCX/TXT)")
    parser.add_argument("--query", type=str, help="Search query to test after ingestion")
    parser.add_argument("--search", type=str, help="Search-only mode (no ingestion)")
    parser.add_argument("--stats", action="store_true", help="Show collection statistics")
    parser.add_argument("--reset", action="store_true", help="Reset the Qdrant collection")
    parser.add_argument("--top-k", type=int, default=5, help="Number of search results")
    args = parser.parse_args()

    from config import settings
    from rag.vector_store import rag_service

    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase C RAG Test")
    print("=" * 60 + "\n")

    # ── Ensure collection ──
    try:
        await rag_service.ensure_collection()
        print("✅ Qdrant connection OK")
    except Exception as e:
        print(f"❌ Qdrant connection failed: {e}")
        print("   Make sure Qdrant is running: docker-compose up qdrant")
        sys.exit(1)

    # ── Stats ──
    if args.stats:
        print("\n[Collection Stats]\n")
        stats = await rag_service.get_collection_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print()
        return 0

    # ── Reset ──
    if args.reset:
        print("\n⚠️  Resetting collection (deleting all data)...")
        await rag_service.reset_collection()
        print("✅ Collection reset\n")
        return 0

    # ── Search only ──
    if args.search:
        print(f"\n[Search] Query: \"{args.search}\"\n")
        start = time.time()
        results = await rag_service.search(query=args.search, top_k=args.top_k)
        elapsed = time.time() - start

        print(f"  Found {len(results)} results in {elapsed:.3f}s\n")
        for i, r in enumerate(results, 1):
            print(f"  [{i}] Score: {r['score']:.4f} | Source: {r['source_type']} | "
                  f"Chunk #{r.get('chunk_index', '?')}")
            meta = r.get("metadata", {})
            if meta.get("page_num"):
                print(f"      Page: {meta['page_num']} | File: {meta.get('filename', 'N/A')}")
            if meta.get("start_time") is not None:
                print(f"      Time: {meta['start_time']:.1f}s - {meta.get('end_time', 0):.1f}s"
                      f" | Speakers: {meta.get('speakers', 'N/A')}")
            print(f"      Text: {r['text'][:150]}...")
            print()
        return 0

    # ── Ingest + Search ──
    if not args.file:
        print("Usage: python scripts/test_rag.py --file document.pdf [--query 'search term']")
        print("       python scripts/test_rag.py --search 'search term'")
        print("       python scripts/test_rag.py --stats")
        return 1

    if not os.path.exists(args.file):
        print(f"❌ File not found: {args.file}")
        return 1

    file_size_mb = os.path.getsize(args.file) / 1024 / 1024
    print(f"📂 Input: {args.file} ({file_size_mb:.1f} MB)")

    # ── Step 1: Extract text ──
    print("\n" + "-" * 40)
    print("  Step 1: Text Extraction")
    print("-" * 40 + "\n")

    from services.text_extraction import text_extractor

    start = time.time()
    extraction = await text_extractor.extract(args.file)
    extract_time = time.time() - start

    text = extraction["text"]
    pages = extraction.get("pages", [])
    meta = extraction.get("metadata", {})

    print(f"  ✅ Extracted in {extract_time:.2f}s")
    print(f"  📄 Pages: {meta.get('page_count', 'N/A')}")
    print(f"  📝 Words: {meta.get('word_count', len(text.split()))}")
    print(f"  📋 Title: {meta.get('title', 'N/A')}")
    print(f"  📖 Preview: {text[:200]}...")

    # ── Step 2: Chunking ──
    print("\n" + "-" * 40)
    print("  Step 2: Page-Aware Chunking")
    print("-" * 40 + "\n")

    chunks = rag_service._chunk_pages(pages, os.path.basename(args.file))
    print(f"  ✅ Generated {len(chunks)} chunks")

    if chunks:
        avg_words = sum(len(c["text"].split()) for c in chunks) / len(chunks)
        print(f"  📊 Average chunk: {avg_words:.0f} words")
        print(f"  📊 Shortest: {min(len(c['text'].split()) for c in chunks)} words")
        print(f"  📊 Longest: {max(len(c['text'].split()) for c in chunks)} words")
        print(f"\n  First chunk preview:")
        print(f"    Page: {chunks[0]['metadata'].get('page_num', 'N/A')}")
        print(f"    Text: {chunks[0]['text'][:200]}...")

    # ── Step 3: Embedding + Storage ──
    print("\n" + "-" * 40)
    print("  Step 3: Embedding + Qdrant Storage")
    print("-" * 40 + "\n")

    source_id = str(uuid.uuid4())

    start = time.time()
    chunk_count = await rag_service.ingest_course_material(
        source_id=source_id,
        filename=os.path.basename(args.file),
        pages=pages,
    )
    embed_time = time.time() - start

    print(f"  ✅ Stored {chunk_count} chunks in {embed_time:.2f}s")
    print(f"  ⏱  {embed_time/max(chunk_count,1):.3f}s per chunk")

    # Cost estimate (OpenAI embeddings: ~$0.02 per 1M tokens)
    total_words = sum(len(c["text"].split()) for c in chunks)
    est_tokens = int(total_words * 1.3)  # rough word→token ratio
    est_cost = (est_tokens / 1_000_000) * 0.02
    print(f"  💰 Estimated embedding cost: ${est_cost:.5f} ({est_tokens} tokens)")

    # ── Step 4: Search ──
    print("\n" + "-" * 40)
    print("  Step 4: Semantic Search")
    print("-" * 40 + "\n")

    # Collection stats
    stats = await rag_service.get_collection_stats()
    print(f"  Collection: {stats.get('points_count', '?')} total points")

    query = args.query or text[:100]  # Use first 100 chars as default query
    print(f"\n  Query: \"{query[:80]}{'...' if len(query) > 80 else ''}\"")

    start = time.time()
    results = await rag_service.search(
        query=query,
        top_k=args.top_k,
        source_id=source_id,
    )
    search_time = time.time() - start

    print(f"  Found {len(results)} results in {search_time:.3f}s\n")

    for i, r in enumerate(results, 1):
        print(f"  [{i}] Score: {r['score']:.4f} | Page: {r['metadata'].get('page_num', 'N/A')} | "
              f"Chunk #{r.get('chunk_index', '?')}")
        print(f"      {r['text'][:150]}...")
        print()

    # ── Validation ──
    print("-" * 40)
    print("  Validation")
    print("-" * 40 + "\n")

    checks = []
    checks.append(("Text extracted (non-empty)", len(text) > 0))
    checks.append(("Chunks generated", len(chunks) > 0))
    checks.append(("Chunks stored in Qdrant", chunk_count > 0))
    checks.append(("Search returns results", len(results) > 0))
    if results:
        checks.append(("Top result score > 0.5", results[0]["score"] > 0.5))
        checks.append(("Results have page metadata", "page_num" in results[0].get("metadata", {})))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)

    for name, ok in checks:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")

    print(f"\n  Results: {passed}/{total} passed\n")

    # Cleanup: delete the test source
    await rag_service.delete_by_source(source_id)
    print(f"  🧹 Cleaned up test data (source_id={source_id[:8]}...)\n")

    return 0 if passed == total else 1


import uuid  # needed for source_id generation

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
