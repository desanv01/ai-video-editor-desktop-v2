# Repository and Version State

## Version baseline

- Branch: `codex/fix-dashboard-project-intake`
- HEAD: `eeb55a47a385e3b2136ac3159a186549b663fe6b` (`Add overhaul setup and run guide`)
- Commit date: `2026-05-28T10:01:20+08:00`
- Working tree: dirty and treated as authoritative.
- At baseline, Git reported 66 tracked changed files, approximately 16,239 insertions and 1,671 deletions, plus untracked implementation, migration, documentation, and asset files.

## Meaningful tree

```text
backend/
  app/agents/          five processing stages and orchestrator
  app/api/routes/      FastAPI routes
  app/db/              SQLAlchemy models/session
  app/providers/       provider registry and adapters
  app/rag/             Qdrant vector store
  app/services/        extraction, review, rendering, evaluation
  app/mcp/             three stdio MCP servers
  app/alembic/         five migration revisions
  tests/               canonical tests
desktop/
  src/                 React 19 client
  src-tauri/           Tauri 2 launcher/bootstrap/installer
  revideo/             optional browser-render helper
docker-compose.yml     development stack
docker-compose.desktop.yml packaged desktop backend stack
docs/                  handoff, setup, and generated audit material
scripts/               setup/evaluation helpers
```

`backend/app/tests/` duplicates many `backend/tests/` files. `desktop/src-tauri/target/` contains generated build copies and is excluded from source statistics. Deleted `n8n/README.md` and `n8n/workflows/pipeline_monitor.json` are pre-overhaul/legacy evidence, not current runtime.

## Overhaul implications

The current tree adds a project domain, multi-source assets, persisted settings, native import, semantic visual/layout planning, teacher review controls, richer export artifacts, evaluation metrics, and desktop bootstrap. Older single-video, n8n-centered, or scene-detection-primary descriptions are obsolete. See `22_CHANGELOG_AND_OVERHAUL_COMPARISON.md`.
