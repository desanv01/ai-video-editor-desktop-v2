# Test and Build Results

| Command | Time | Exit | Result | Interpretation/reproducibility |
|---|---:|---:|---|---|
| `.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_*.py -v` in managed sandbox | 18.01 s | 1 | 109 tests reached before 23 errors | Failures were dominated by test-order module stubs and Windows temp permissions. See `_backend_tests.log`. |
| isolated execution of 24 canonical test files | per-file, total under 30 s | mixed | 14 files passed, 10 failed | Failures: incomplete `sqlalchemy`/`pydantic_settings` stubs in test process or temp-directory access. See `_backend_isolated_summary.csv` and log. |
| same canonical discovery outside managed sandbox | 31.914 s test time; 38 s wall time | 0 | 191 tests passed | Successful and reproducible with normal Windows temp/process permissions; one SWIG deprecation warning. |
| `npm run build` in `desktop` (managed sandbox) | 31.4 s | 1 | Vite/esbuild `spawn EPERM` | Sandbox execution-policy artifact. |
| `npm run build` outside sandbox | 69 s | 0 | 1598 modules; production build completed | Successful TypeScript/Vite build during this audit. |
| `cargo check` in `desktop/src-tauri` | 233.7 s | 0 | Rust desktop shell compiled in dev/check profile | Successful; initial wait included a build-directory lock. |
| `docker compose config --quiet` | 1.67 s | 0 | valid development Compose | Reproducible. |
| `docker compose -f docker-compose.desktop.yml config --quiet` without launcher env | 3.59 s | 1 | empty bind-mount source due missing `AIVE_HOST_*` | Expected only when bypassing Tauri launcher; operational constraint, not YAML syntax error. |

The managed-sandbox discovery errors must not be reported as product regressions because the same canonical suite passed all 191 tests outside that sandbox. They remain useful evidence that the suite is sensitive to module stubbing and Windows temp/process restrictions. Conversely, successful unit/build checks do not prove backend/provider/render end-to-end behavior.

No paid-provider, destructive database, browser E2E, installed-app, clean-machine, or five-video long-media test was run.
