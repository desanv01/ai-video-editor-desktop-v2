# API Endpoint and Schema Inventory

`API_ENDPOINTS.csv` contains 115 decorated handlers from the current tree, including 13 debug handlers that are only mounted when `APP_DEBUG` is enabled. Main routers are mounted under `/api/v1`; project routes add `/projects` (`backend/app/main.py:70-77`). Root and health remain top-level.

| Category | Count |
|---|---:|
| analysis | 2 |
| assets | 2 |
| edit plans | 16 |
| evaluation/logging | 5 |
| health/settings | 10 |
| legacy/unused | 13 |
| materials/RAG | 2 |
| projects | 33 |
| rendering/export | 12 |
| transcription | 5 |
| videos | 11 |
| visual planning | 4 |

No authentication dependency was found. Upload/render handlers can mutate both database and filesystem state; analysis routes can call configured AI providers. `API_FRONTEND_MAPPING.csv` provides a conservative static mapping, and entries marked for manual inspection should not be interpreted as disconnected solely because symbol names differ.

Risks: browser default `localhost:8000` differs from packaged desktop `127.0.0.1:18000`; debug routes depend on `APP_DEBUG`; error payload styles vary; some implemented endpoints have no visible UI caller; MCP tools are not HTTP endpoints; name-based mapping cannot prove runtime calls.
