# Limitations, TODOs, and Technical Debt

| Issue | Severity | User impact | Thesis impact | Evidence | Recommended description |
|---|---|---|---|---|---|
| No authentication/authorization | High | Any local/network caller can mutate data | Must not claim secure multi-user deployment | API routes have no auth dependency | Prototype/local deployment limitation |
| Scanned PDF OCR absent | High | Empty/weak material extraction | Limits RAG claims | backend/app/services/text_extraction.py | Text-based PDFs are supported; scanned PDFs need OCR |
| Redis configured but no consumer found | Medium | Extra operational dependency | Do not claim caching/queue use | docker-compose.yml:73-79 | Provisioned but not evidenced as active |
| LangGraph installed but unused | Low | Dependency complexity | Do not describe LangGraph orchestration | backend/requirements.txt:21 | Direct asyncio orchestration is active |
| MCP disconnected from core UI | Medium | Optional tools may drift | Do not claim MCP powers workflow | backend/app/mcp/run_mcp.py | Optional integration surface |
| Desktop Compose requires launcher variables | High | Raw compose fails validation | Deployment reproducibility caveat | docker-compose.desktop.yml | Start through packaged launcher or provide AIVE_HOST_* |
| Duplicate test trees | Medium | Discovery/order confusion | Test-count caveat | backend/tests; backend/app/tests | Canonical test root must be stated |
| No frontend/E2E suite | High | UI regressions may escape | Readiness limitation | No frontend test configuration found | Frontend build passes but behavior needs smoke tests |
| No active-time telemetry | High | Main evaluation metric needs manual timer | Chapter 4 collection requirement | No persisted active editing timer | Use external timer for five-video study |
| Hard-coded default ports differ | Medium | Browser/desktop data-stack confusion | Architecture clarification | desktop/src/lib/api.ts; desktop/src-tauri/src/lib.rs:233-245 | Browser 8000 and desktop 18000 are separate defaults |

The static keyword scan found 34 TODO/FIXME/HACK/placeholder-like hits after exclusions. Keyword hits are leads, not automatic defects. Hidden legacy UI blocks, placeholder provider adapters, disabled Revideo default, stale MCP behavior, and deleted n8n files are classified according to runtime connectivity rather than comments alone.

## Resolved post-audit regression

The pack originally did not include a real failure case for large slide-deck slideshow generation. On June 16, 2026, project `test23` exposed one: a 36-page PDF deck failed during generated-slide-video creation because the previous FFmpeg command scaled and concatenated too many simultaneous page inputs. That issue has since been fixed by switching multi-page slideshow generation to an FFconcat single-stream path in `backend/app/services/ffmpeg.py:1621-1706`. The remaining limitation is not the same bug; it is broader long-form render validation across more cases.
