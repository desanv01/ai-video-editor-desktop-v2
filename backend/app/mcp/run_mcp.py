#!/usr/bin/env python3
"""
MCP Server Runner — Entry point for starting MCP servers.

Usage:
    # Run a specific server:
    python -m mcp.run_mcp video_tools
    python -m mcp.run_mcp knowledge_tools
    python -m mcp.run_mcp pipeline_tools

    # Or run directly:
    python backend/app/mcp/run_mcp.py video_tools

Each server communicates over stdio using the MCP protocol.
Configure in Claude Desktop or any MCP-compatible client.
"""

import sys
import os
import asyncio

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load environment variables
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_mcp.py <server_name>")
        print("Available servers:")
        print("  video_tools      — FFmpeg video/audio operations")
        print("  knowledge_tools  — RAG knowledge base operations")
        print("  pipeline_tools   — Pipeline orchestration & management")
        sys.exit(1)

    server_name = sys.argv[1]

    if server_name == "video_tools":
        from mcp.video_tools_server import main as server_main
    elif server_name == "knowledge_tools":
        from mcp.knowledge_tools_server import main as server_main
    elif server_name == "pipeline_tools":
        from mcp.pipeline_tools_server import main as server_main
    else:
        print(f"Unknown server: {server_name}")
        sys.exit(1)

    asyncio.run(server_main())


if __name__ == "__main__":
    main()
