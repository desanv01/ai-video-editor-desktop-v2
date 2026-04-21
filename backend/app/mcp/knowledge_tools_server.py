"""
MCP Knowledge Tools Server

Exposes RAG and knowledge base operations as MCP tools.

Tools:
  - knowledge_search: Semantic search across course materials and transcripts
  - knowledge_ingest_material: Upload and embed a course material document
  - knowledge_list_materials: List all ingested course materials
  - knowledge_delete_material: Remove a material from the knowledge base
  - knowledge_extract_text: Extract text from a document (PDF/PPTX/DOCX)
  - knowledge_collection_stats: Get vector database statistics

This enables an LLM agent to query the knowledge base during analysis —
e.g., "Is this transcript segment about a topic covered in the lecture notes?"
"""

import os
import sys
import json
import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp.server.models import InitializationOptions

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

server = Server("ai-video-editor-knowledge-tools")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge_search",
            description=(
                "Semantic search across the knowledge base (course materials + transcripts). "
                "Returns the most relevant text chunks with similarity scores."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query (natural language)"},
                    "top_k": {"type": "integer", "description": "Number of results to return (default: 5)", "default": 5},
                    "source_type": {
                        "type": "string",
                        "enum": ["course_material", "transcript", "all"],
                        "description": "Filter by source type (default: all)",
                        "default": "all",
                    },
                    "score_threshold": {
                        "type": "number",
                        "description": "Minimum similarity score 0-1 (default: 0.3)",
                        "default": 0.3,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="knowledge_ingest_material",
            description=(
                "Ingest a course material document into the knowledge base. "
                "Extracts text, chunks it, computes embeddings, and stores in the vector DB. "
                "Supports PDF, PPTX, DOCX, and TXT files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                    "source_id": {"type": "string", "description": "Unique identifier for this material (e.g. UUID)"},
                },
                "required": ["file_path", "source_id"],
            },
        ),
        Tool(
            name="knowledge_ingest_transcript",
            description=(
                "Embed transcript segments into the knowledge base for semantic search. "
                "Chunks the transcript into ~60-second speaker-aware segments."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "Video ID that owns this transcript"},
                    "segments": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Raw transcript segments (from ASR output)",
                    },
                },
                "required": ["source_id", "segments"],
            },
        ),
        Tool(
            name="knowledge_list_materials",
            description="List all course materials currently in the knowledge base with their metadata.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="knowledge_delete_material",
            description="Remove a specific course material from the knowledge base by its source ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "The source_id of the material to delete"},
                },
                "required": ["source_id"],
            },
        ),
        Tool(
            name="knowledge_extract_text",
            description=(
                "Extract plain text from a document file (PDF, PPTX, DOCX, TXT). "
                "Returns the text content without embedding it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the document file"},
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="knowledge_collection_stats",
            description="Get statistics about the vector database collection (point count, dimensions, etc.).",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    from rag.vector_store import rag_service
    from services.text_extraction import text_extractor

    try:
        await rag_service.ensure_collection()

        if name == "knowledge_search":
            source_type = arguments.get("source_type", "all")
            results = await rag_service.search(
                query=arguments["query"],
                top_k=arguments.get("top_k", 5),
                source_type=source_type if source_type != "all" else None,
                score_threshold=arguments.get("score_threshold", 0.3),
            )
            return [TextContent(type="text", text=json.dumps({
                "results": results, "count": len(results),
            }, indent=2))]

        elif name == "knowledge_ingest_material":
            file_path = arguments["file_path"]
            source_id = arguments["source_id"]

            # Extract text
            pages = text_extractor.extract(file_path)
            full_text = "\n\n".join(p["text"] for p in pages if p.get("text"))

            # Ingest into vector DB
            chunk_count = await rag_service.ingest_course_material(
                source_id=source_id,
                filename=os.path.basename(file_path),
                pages=pages,
            )

            return [TextContent(type="text", text=json.dumps({
                "status": "success",
                "source_id": source_id,
                "filename": os.path.basename(file_path),
                "pages_extracted": len(pages),
                "chunks_embedded": chunk_count,
                "text_length": len(full_text),
            }))]

        elif name == "knowledge_ingest_transcript":
            chunk_count = await rag_service.ingest_transcript(
                source_id=arguments["source_id"],
                segments=arguments["segments"],
                target_duration=60.0,
            )
            return [TextContent(type="text", text=json.dumps({
                "status": "success",
                "source_id": arguments["source_id"],
                "chunks_embedded": chunk_count,
            }))]

        elif name == "knowledge_list_materials":
            # Use Qdrant scroll to find unique source_ids
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            points = await rag_service.client.scroll(
                collection_name=rag_service.collection_name,
                scroll_filter=Filter(must=[
                    FieldCondition(key="source_type", match=MatchValue(value="course_material")),
                ]),
                limit=100,
                with_payload=True,
                with_vectors=False,
            )

            sources = {}
            for point in points[0]:
                sid = point.payload.get("source_id", "unknown")
                if sid not in sources:
                    sources[sid] = {
                        "source_id": sid,
                        "filename": point.payload.get("filename", "unknown"),
                        "chunks": 0,
                    }
                sources[sid]["chunks"] += 1

            return [TextContent(type="text", text=json.dumps({
                "materials": list(sources.values()),
                "total": len(sources),
            }, indent=2))]

        elif name == "knowledge_delete_material":
            await rag_service.delete_by_source(arguments["source_id"])
            return [TextContent(type="text", text=json.dumps({
                "status": "deleted", "source_id": arguments["source_id"],
            }))]

        elif name == "knowledge_extract_text":
            pages = text_extractor.extract(arguments["file_path"])
            return [TextContent(type="text", text=json.dumps({
                "filename": os.path.basename(arguments["file_path"]),
                "pages": len(pages),
                "text": "\n\n".join(p["text"] for p in pages if p.get("text"))[:5000],
                "truncated": len("\n\n".join(p["text"] for p in pages)) > 5000,
            }, indent=2))]

        elif name == "knowledge_collection_stats":
            info = await rag_service.client.get_collection(rag_service.collection_name)
            return [TextContent(type="text", text=json.dumps({
                "collection": rag_service.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": str(info.status),
            }, indent=2))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="ai-video-editor-knowledge-tools",
                server_version="1.0.0",
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
