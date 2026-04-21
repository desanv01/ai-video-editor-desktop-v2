#!/usr/bin/env python3
"""
Phase I Test Script — MCP Server Validation
=============================================

Tests that all three MCP servers register their tools correctly
and that basic tool calls work.

Usage:
    python scripts/test_mcp.py

    # Test a specific server:
    python scripts/test_mcp.py --server video_tools
    python scripts/test_mcp.py --server knowledge_tools
    python scripts/test_mcp.py --server pipeline_tools

Prerequisites:
    - All Docker services running (PostgreSQL, Qdrant)
    - pip install mcp (MCP SDK)
"""

import asyncio
import argparse
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))


async def test_video_tools():
    """Test video tools server registration and basic calls."""
    print("\n  🎬 Video Tools Server")
    print("  " + "─" * 40)

    from mcp.video_tools_server import server, list_tools, call_tool

    # Test tool listing
    tools = await list_tools()
    tool_names = [t.name for t in tools]
    print(f"  Registered tools: {len(tools)}")
    for t in tools:
        print(f"    • {t.name}: {t.description[:60]}...")

    expected = ["video_metadata", "video_extract_audio", "video_trim",
                "video_concat", "video_detect_silence", "video_extract_frame",
                "subtitle_generate", "subtitle_burn"]

    checks = []
    for name in expected:
        ok = name in tool_names
        checks.append((f"Tool '{name}' registered", ok))

    # Test subtitle_generate (doesn't need a real file)
    result = await call_tool("subtitle_generate", {
        "segments": [
            {"text": "Hello world", "start": 0.0, "end": 2.0},
            {"text": "This is a test", "start": 2.0, "end": 4.0},
        ],
        "output_path": "/tmp/test_srt.srt",
    })
    srt_ok = "success" in result[0].text
    checks.append(("subtitle_generate call works", srt_ok))

    # Cleanup
    try:
        os.remove("/tmp/test_srt.srt")
    except OSError:
        pass

    return checks


async def test_knowledge_tools():
    """Test knowledge tools server registration."""
    print("\n  🧠 Knowledge Tools Server")
    print("  " + "─" * 40)

    from mcp.knowledge_tools_server import server, list_tools, call_tool

    tools = await list_tools()
    tool_names = [t.name for t in tools]
    print(f"  Registered tools: {len(tools)}")
    for t in tools:
        print(f"    • {t.name}: {t.description[:60]}...")

    expected = ["knowledge_search", "knowledge_ingest_material",
                "knowledge_ingest_transcript", "knowledge_list_materials",
                "knowledge_delete_material", "knowledge_extract_text",
                "knowledge_collection_stats"]

    checks = []
    for name in expected:
        ok = name in tool_names
        checks.append((f"Tool '{name}' registered", ok))

    # Test collection stats (requires Qdrant running)
    try:
        result = await call_tool("knowledge_collection_stats", {})
        data = json.loads(result[0].text)
        stats_ok = "collection" in data or "error" in data
        checks.append(("knowledge_collection_stats callable", stats_ok))
    except Exception as e:
        checks.append(("knowledge_collection_stats callable", False))
        print(f"    ⚠️  Stats call failed (Qdrant running?): {e}")

    return checks


async def test_pipeline_tools():
    """Test pipeline tools server registration."""
    print("\n  🔧 Pipeline Tools Server")
    print("  " + "─" * 40)

    from mcp.pipeline_tools_server import server, list_tools, call_tool

    tools = await list_tools()
    tool_names = [t.name for t in tools]
    print(f"  Registered tools: {len(tools)}")
    for t in tools:
        print(f"    • {t.name}: {t.description[:60]}...")

    expected = ["pipeline_list_videos", "pipeline_video_status",
                "pipeline_run_agent", "pipeline_get_segments",
                "pipeline_get_plan", "pipeline_update_segment",
                "pipeline_approve_plan", "pipeline_revalidate",
                "pipeline_quality_report", "pipeline_get_chapters"]

    checks = []
    for name in expected:
        ok = name in tool_names
        checks.append((f"Tool '{name}' registered", ok))

    # Test list_videos (requires DB running)
    try:
        result = await call_tool("pipeline_list_videos", {})
        data = json.loads(result[0].text)
        list_ok = "videos" in data or "error" in data
        checks.append(("pipeline_list_videos callable", list_ok))
    except Exception as e:
        checks.append(("pipeline_list_videos callable", False))
        print(f"    ⚠️  List call failed (DB running?): {e}")

    return checks


async def main():
    parser = argparse.ArgumentParser(description="Test MCP servers")
    parser.add_argument("--server", type=str, help="Test specific server only")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  AI Video Editing Agent — Phase I MCP Server Test")
    print("=" * 60)

    all_checks = []

    servers = {
        "video_tools": test_video_tools,
        "knowledge_tools": test_knowledge_tools,
        "pipeline_tools": test_pipeline_tools,
    }

    if args.server:
        if args.server not in servers:
            print(f"Unknown server: {args.server}")
            return 1
        checks = await servers[args.server]()
        all_checks.extend(checks)
    else:
        for name, test_fn in servers.items():
            try:
                checks = await test_fn()
                all_checks.extend(checks)
            except Exception as e:
                print(f"  ❌ Server '{name}' test failed: {e}")
                all_checks.append((f"Server '{name}' loads", False))

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Validation Summary")
    print(f"{'=' * 60}\n")

    for name, ok in all_checks:
        print(f"  {'✅' if ok else '❌'} {name}")

    passed = sum(1 for _, ok in all_checks if ok)
    total = len(all_checks)

    print(f"\n  Results: {passed}/{total} passed")
    if passed == total:
        print(f"  🎉 ALL MCP SERVERS VALIDATED!")
    else:
        print(f"  ⚠️  {total - passed} checks failed")
    print()

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
