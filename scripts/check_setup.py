#!/usr/bin/env python3
"""
Phase A Validation Script
=========================
Run this after `docker-compose up -d` to verify the entire infrastructure is healthy.

Usage:
    python scripts/check_setup.py            # Run from project root
    docker exec aive-backend python scripts/check_setup.py  # Run inside container

Checks:
  1. Environment variables / API keys
  2. PostgreSQL connection
  3. Qdrant connection
  4. Redis connection
  5. ffmpeg / ffprobe availability
  6. n8n availability
  7. FastAPI health endpoint
"""

import asyncio
import os
import sys
import subprocess
import json

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
results = []


def check(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append({"name": name, "passed": passed, "detail": detail})
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))


async def main():
    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase A Setup Validation")
    print("=" * 60 + "\n")

    # ──────────────────────────────────────
    # 1. Environment Variables
    # ──────────────────────────────────────
    print("[1/7] Environment Variables\n")

    from config import settings

    check(
        "MISTRAL_API_KEY",
        bool(settings.MISTRAL_API_KEY) and settings.MISTRAL_API_KEY != "...",
        "Required for Voxtral ASR (primary)"
    )
    check(
        "DEEPSEEK_API_KEY",
        bool(settings.DEEPSEEK_API_KEY) and settings.DEEPSEEK_API_KEY != "sk-...",
        "Required for LLM reasoning (Agents 2, 3, 5)"
    )
    check(
        "OPENAI_API_KEY",
        bool(settings.OPENAI_API_KEY) and settings.OPENAI_API_KEY != "sk-...",
        "Required for embeddings + Whisper fallback"
    )
    check(
        "ASR_PROVIDER",
        settings.ASR_PROVIDER in ("voxtral", "whisper"),
        f"Current: {settings.ASR_PROVIDER}"
    )
    check(
        "DATABASE_URL",
        "postgresql" in settings.DATABASE_URL,
        settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "configured"
    )

    # ──────────────────────────────────────
    # 2. PostgreSQL
    # ──────────────────────────────────────
    print("\n[2/7] PostgreSQL\n")

    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        async with engine.connect() as conn:
            result = await conn.execute(
                __import__("sqlalchemy").text("SELECT version()")
            )
            version = result.scalar()
        await engine.dispose()
        check("PostgreSQL connection", True, version[:50] if version else "connected")
    except Exception as e:
        check("PostgreSQL connection", False, str(e)[:80])

    # ──────────────────────────────────────
    # 3. Qdrant
    # ──────────────────────────────────────
    print("\n[3/7] Qdrant\n")

    try:
        from qdrant_client import QdrantClient
        qclient = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=5)
        collections = qclient.get_collections()
        check(
            "Qdrant connection",
            True,
            f"{len(collections.collections)} collections found"
        )
    except Exception as e:
        check("Qdrant connection", False, str(e)[:80])

    # ──────────────────────────────────────
    # 4. Redis
    # ──────────────────────────────────────
    print("\n[4/7] Redis\n")

    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=5)
        pong = r.ping()
        check("Redis connection", pong, "PONG received")
    except Exception as e:
        check("Redis connection", False, str(e)[:80])

    # ──────────────────────────────────────
    # 5. ffmpeg / ffprobe
    # ──────────────────────────────────────
    print("\n[5/7] FFmpeg\n")

    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        check("ffmpeg", result.returncode == 0, version_line[:60])
    except Exception as e:
        check("ffmpeg", False, str(e)[:80])

    try:
        result = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, timeout=5)
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        check("ffprobe", result.returncode == 0, version_line[:60])
    except Exception as e:
        check("ffprobe", False, str(e)[:80])

    # ──────────────────────────────────────
    # 6. n8n
    # ──────────────────────────────────────
    print("\n[6/7] n8n\n")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://n8n:5678/healthz")
            check("n8n health", resp.status_code == 200, f"HTTP {resp.status_code}")
    except Exception as e:
        err = str(e)[:80]
        # n8n might not be reachable from inside the backend container by service name
        # This is expected if running the script outside Docker
        check("n8n health", False, f"{err} (OK if running outside Docker)")

    # ──────────────────────────────────────
    # 7. Storage directories
    # ──────────────────────────────────────
    print("\n[7/7] Storage Directories\n")

    for path_name, path_val in [
        ("VIDEO_STORAGE_PATH", settings.VIDEO_STORAGE_PATH),
        ("UPLOAD_PATH", settings.UPLOAD_PATH),
        ("TEMP_PATH", settings.TEMP_PATH),
    ]:
        exists = os.path.isdir(path_val)
        if not exists:
            try:
                os.makedirs(path_val, exist_ok=True)
                check(path_name, True, f"Created {path_val}")
            except Exception as e:
                check(path_name, False, f"Cannot create {path_val}: {e}")
        else:
            check(path_name, True, f"{path_val} exists")

    # ──────────────────────────────────────
    # Summary
    # ──────────────────────────────────────
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} passed" + (f", {failed} failed" if failed else ""))
    print("=" * 60)

    if failed > 0:
        print(f"\n{FAIL} {failed} check(s) failed. Fix the issues above before proceeding.\n")
        # Separate critical vs warning failures
        critical_fails = [r for r in results if not r["passed"] and "API_KEY" in r["name"]]
        if critical_fails:
            print("  Critical: Set your API keys in .env before running the pipeline.\n")
        sys.exit(1)
    else:
        print(f"\n{PASS} All checks passed! Phase A infrastructure is ready.\n")
        print("  Next steps:")
        print("    1. Open http://localhost:8000/docs — Swagger API docs")
        print("    2. Open http://localhost:5678 — n8n workflow editor")
        print("    3. Open http://localhost:6333/dashboard — Qdrant vector DB")
        print("    4. Try: curl -X POST http://localhost:8000/api/v1/videos/upload -F 'file=@lecture.mp4'")
        print()
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
