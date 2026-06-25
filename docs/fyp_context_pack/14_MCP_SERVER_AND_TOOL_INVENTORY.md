# MCP Server and Tool Inventory

The claim is exactly confirmed: three stdio MCP servers expose 25 tools. `video-tools` has 8, `knowledge-tools` has 7, and `pipeline-tools` has 10. No MCP resources or prompt templates were found. Registration uses `Server`, `list_tools`, and `call_tool`; `backend/app/mcp/run_mcp.py` is the entry point.

MCP_TOOLS.csv lists every tool and status. The servers wrap media, Qdrant, and pipeline operations, but no FastAPI mounting, React call, or normal desktop dependency was found. Therefore MCP is an IMPLEMENTED_BUT_NOT_CONNECTED integration layer, not a core runtime requirement. The pipeline approval tool appears less complete than the current persistent render-job API and is marked PARTIALLY_IMPLEMENTED.

Security implications include broad local file/media operations, database access, no application authentication layer, stdio-client trust, and configuration examples that must never contain live credentials. Missing MCP coverage includes the full current project-first UI semantics, native desktop import lifecycle, and some newer render/export operations.
