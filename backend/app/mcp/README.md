# MCP Servers — Model Context Protocol Integration

## Overview

The AI Video Editing system exposes its capabilities through three MCP servers.
This allows any MCP-compatible LLM client (Claude Desktop, n8n, custom agents)
to control the video editing pipeline through tool calls.

**Why MCP?** LLMs cannot edit videos directly. MCP servers convert AI reasoning
into real actions — `video.trim(start, end)`, `knowledge.search(query)`,
`pipeline.approve_plan(video_id)`.

## Three Servers

### 1. Video Tools (`video_tools`)
FFmpeg operations for direct video/audio manipulation.

| Tool | Description |
|------|-------------|
| `video_metadata` | Get duration, resolution, fps, codecs |
| `video_extract_audio` | Extract audio track → WAV |
| `video_trim` | Trim segment by start/end time |
| `video_concat` | Concatenate multiple clips |
| `video_detect_silence` | Find silence regions in audio |
| `video_extract_frame` | Extract frame at timestamp → JPEG |
| `subtitle_generate` | Generate SRT from segment data |
| `subtitle_burn` | Hardcode subtitles into video |

### 2. Knowledge Tools (`knowledge_tools`)
RAG knowledge base for course materials and transcripts.

| Tool | Description |
|------|-------------|
| `knowledge_search` | Semantic search across materials + transcripts |
| `knowledge_ingest_material` | Upload + embed a document (PDF/PPTX/DOCX) |
| `knowledge_ingest_transcript` | Embed transcript segments for RAG |
| `knowledge_list_materials` | List all ingested course materials |
| `knowledge_delete_material` | Remove material from knowledge base |
| `knowledge_extract_text` | Extract text from document (no embedding) |
| `knowledge_collection_stats` | Vector DB statistics |

### 3. Pipeline Tools (`pipeline_tools`)
Pipeline orchestration and management.

| Tool | Description |
|------|-------------|
| `pipeline_list_videos` | List all videos with status |
| `pipeline_video_status` | Detailed status + progress + timing |
| `pipeline_run_agent` | Run a specific analysis agent |
| `pipeline_get_segments` | Get analyzed segments with scores |
| `pipeline_get_plan` | Get current edit plan |
| `pipeline_update_segment` | Teacher override (change action) |
| `pipeline_approve_plan` | Approve plan + trigger render |
| `pipeline_revalidate` | Check plan coherence after changes |
| `pipeline_quality_report` | Get quality metrics |
| `pipeline_get_chapters` | Get auto-generated chapter markers |

**Total: 25 MCP tools across 3 servers.**

## Setup

### Prerequisites
```bash
# Install MCP SDK
pip install mcp

# Ensure all services are running
docker-compose up -d
```

### Running a Server

```bash
cd ai-video-editor

# Run a specific server (stdio mode):
python backend/app/mcp/run_mcp.py video_tools
python backend/app/mcp/run_mcp.py knowledge_tools
python backend/app/mcp/run_mcp.py pipeline_tools
```

### Claude Desktop Configuration

Copy `mcp_config.json` to your Claude Desktop config directory:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Edit the paths and API keys in the config file, then restart Claude Desktop.

### n8n Integration

Use n8n's **MCP Client** node to connect to any of the three servers.
The servers run over stdio, so n8n needs to spawn the Python process.

### Test the Servers

```bash
# Test all three servers:
python scripts/test_mcp.py

# Test a specific server:
python scripts/test_mcp.py --server video_tools
```

## Example LLM Conversation

With the MCP servers connected, an LLM can have conversations like:

**User:** "Process the lecture video I uploaded yesterday and cut out all the filler words."

**LLM (using MCP tools):**
1. `pipeline_list_videos()` → finds the latest uploaded video
2. `pipeline_run_agent(video_id, "transcription")` → transcribes
3. `pipeline_run_agent(video_id, "content_understanding")` → analyzes content
4. `pipeline_run_agent(video_id, "fluency")` → detects fillers
5. `pipeline_run_agent(video_id, "edit_planner")` → generates plan
6. `pipeline_get_segments(video_id)` → shows segments with filler counts
7. `pipeline_approve_plan(video_id)` → triggers rendering

**User:** "Actually, keep segment 5 — that Q&A is important."

**LLM:**
1. `pipeline_update_segment(video_id, segment_5_id, "keep", "Q&A is important")`
2. `pipeline_revalidate(video_id)` → checks for coherence issues
3. `pipeline_approve_plan(video_id)` → re-renders

## Architecture

```
┌─────────────────────┐
│   MCP Client        │  Claude Desktop / n8n / Custom Agent
│   (LLM + Tools)     │
└──────────┬──────────┘
           │ stdio (JSON-RPC)
           │
┌──────────┴──────────┐
│   MCP Servers       │
│  ┌────────────────┐ │
│  │ video_tools    │─┼──→ FFmpeg (trim, concat, srt, ...)
│  │ knowledge_tools│─┼──→ Qdrant + OpenAI Embeddings
│  │ pipeline_tools │─┼──→ PostgreSQL + Analysis Agents
│  └────────────────┘ │
└─────────────────────┘
```
