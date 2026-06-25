# FYP Context Pack

This package is a code-grounded audit for **AI-Agent Assisted Video Editing Framework for Automated Generation of Educational Content**. It is intended to support thesis Chapters 1-5, a technical paper, figure recreation, and a five-video evaluation without converting planned or external values into project results.

## Audit baseline

| Item | Value |
|---|---|
| Audit timestamp | 2026-06-15 22:21:14 +08:00 |
| Branch | `codex/fix-dashboard-project-intake` |
| HEAD | `eeb55a47a385e3b2136ac3159a186549b663fe6b` |
| HEAD date | `2026-05-28T10:01:20+08:00` |
| Working tree | Dirty; current tracked and untracked files were audited |
| Network use | None |
| Source modifications | None; outputs are confined to `docs/fyp_context_pack/` |

## Method

The audit combined Git state inspection, AST/static parsing, targeted source reading, dependency/configuration inspection, safe tests, frontend production build, Rust checking, and Docker Compose validation. Machine-readable inventories were generated from the current working tree. Secrets were not read into the reports and are represented as `[REDACTED]`.

## Verification commands

`git status --short`, `git log`, `git diff --stat`, repository `rg` searches, Python AST inventory, `.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_*.py -v`, isolated test-file execution, `npm run build`, `cargo check`, `docker compose config --quiet`, and `docker compose -f docker-compose.desktop.yml config --quiet`.

## Reading order

Start with `01`, `03`, `04`, `05`, `07`, `09`, `16`, `17`, and `25`. For the post-audit render regression and fix, also read `27_RENDER_FIX_UPDATE_2026-06-16.md`. Use `26_MASTER_EVIDENCE_INDEX.md`, CSV inventories, and `project_ground_truth.json` for rapid verification.

## Limitations

No paid AI request, destructive database action, clean-machine installer test, full browser/desktop end-to-end replay, human study, or five-video timing study was performed. A successful build does not prove runtime services or provider credentials. Raw desktop Compose validation requires launcher-created `AIVE_HOST_*` variables. Screenshots were not captured because launching a second stateful desktop/backend stack was unnecessary for static audit evidence.

## Post-audit update

After the original pack was generated, a real localhost render regression was reproduced on June 16, 2026 using project `test23`: a 29:54 video with a 36-page PDF slide deck failed at 12 percent during slideshow generation. That issue, its root cause, the code fix, and live verification have been added to `27_RENDER_FIX_UPDATE_2026-06-16.md` and summarized in the rendering, testing, and final-verdict files.
