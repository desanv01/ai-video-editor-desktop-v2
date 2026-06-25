# Testing, Build, and Quality Status

See `TEST_RESULTS.md` and `TEST_INVENTORY.csv` for command and test-level detail. The tree contains backend unit/service tests for agents, layouts, rendering, imports, projects, evaluation, timelines, and export artifacts. Many tests use mocks/stubs. No frontend component/E2E test framework, code-coverage report, or CI workflow was found during this audit.

Static quality signals include Pydantic schemas, TypeScript compilation, Rust compilation, deterministic validators, and targeted tests. Risks include duplicate test trees (`backend/tests` and `backend/app/tests`), test-order module contamination in discovery, Windows temp-permission sensitivity, no authenticated API tests, no clean-machine installer test, no live provider integration suite, and no five-video full-stack regression suite.

## Post-audit regression verification on 2026-06-16

The original pack predated a real render regression discovered during localhost use of project `test23`. The regression and its fix were verified with both unit tests and live runtime evidence.

Additional verification performed after the original pack:

| Command or check | Result | Interpretation |
|---|---|---|
| `.venv\Scripts\python.exe -m unittest backend.tests.test_picture_in_picture_renderer -v` | 38 passed | Confirms slideshow and FFmpeg error-reporting changes did not break the renderer test surface. |
| `.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_*.py` | 193 passed | Full canonical backend suite still passes after the slideshow fix. |
| Real 36-page slideshow reproduction inside localhost backend | old path failed, new FFconcat path succeeded | Confirms the root cause was the many-input FFmpeg slideshow graph, not the slide content itself. |
| Live retry of project `test23` via `POST /api/v1/videos/{video_id}/plan/approve` | advanced beyond 12 percent into native semantic composition | Confirms the fixed backend passes the previous failure boundary in the actual localhost workflow. |

New targeted tests were added in `backend/tests/test_picture_in_picture_renderer.py:293-334` to cover multi-image FFconcat slideshow construction and FFmpeg tail-error preservation.
