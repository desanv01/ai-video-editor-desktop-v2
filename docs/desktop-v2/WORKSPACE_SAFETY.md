# Desktop V2 — Workspace Safety Rules

These rules apply to every Desktop V2 phase and every agent or script working on it.

## Immutable source perimeter

The following paths are protected original/demo/release workspaces:

    C:\Users\Dv\Desktop\ai-video-editor
    C:\Users\Dv\Desktop\ai-video-editor-viva-clean
    C:\Users\Dv\Desktop\ai-video-editor-standalone-release-work

Do not edit, clean, reset, stash, checkout, delete, install into, build in, launch services from, or copy files to or from these paths. Do not use them as a comparison source. A task that appears to require one of these actions is blocked until the owner provides a new, explicitly scoped worktree.

The only implementation root for this line is:

    C:\Users\Dv\.codex\worktrees\3364\ai-video-editor

Before work, confirm the root with:

    Get-Location
    git rev-parse --show-toplevel

The read-only verifier at scripts/desktop-v2/Verify-DesktopV2Baseline.ps1 must fail when its current directory or resolved repository root is one of the protected paths or a child of one.

## Git safety

- Start from a clean, identified commit and record branch, HEAD, remote and status.
- Use a codex/ branch for implementation. Do not rewrite history or force-push without explicit authorization.
- Review git status --short and git diff --stat before and after each phase.
- Never use git reset --hard, git clean, broad checkout, or destructive file commands to make a check pass.
- Do not stage files by wildcard until the complete staged list has been inspected.
- Commit only the phase deliverables and source changes that were explicitly requested.

## Data and artifact prohibitions

Never copy, stage, commit, package or log any of the following:

- .env, .env.local, provider API keys, access tokens, private keys, certificates or credential stores;
- uploaded recordings, course material, screenshots containing private data, generated exports or database dumps;
- PostgreSQL/Qdrant/Redis volumes, application logs containing request data, backups or crash dumps;
- downloaded ASR/LLM/embedding models or model caches;
- runtime ZIPs, installers, container layers, binaries, node_modules, Rust target, Python environments, dist, build, temporary files or caches.

.env.example, synthetic fixtures under fixtures/synthetic_media, small text fixtures and source documentation are allowed when they contain no live values. The existing docs/fyp_context_pack.zip is documentation evidence, not a runtime package; do not add similar archives for Desktop V2.

## Development-path preservation

- Keep docker-compose.yml as the localhost development implementation and test it independently.
- Do not make browser development depend on the standalone component manager.
- Do not replace the existing backend, API, renderer or React workflow as part of a baseline/documentation phase.
- Keep standalone data under the application-owned data root; never point it at a source checkout or a protected Desktop folder.
- If a test needs media or a database, use synthetic fixtures and an isolated temporary directory inside the worktree or the operating system temporary directory. Remove only artifacts created by that test and only when the test contract permits it.

## Verification and reporting

Every phase must report:

1. Exact worktree path and commit before changes.
2. Files changed and why.
3. Commands run, exit codes and relevant output classification.
4. Whether the result is a source defect, missing dependency, network/sandbox restriction or expected operational prerequisite.
5. Confirmation that protected paths were not touched and no private/runtime artifact was staged.

Do not suppress failures, replace them with a different command, or claim a clean-machine result from a source-tree build. A successful static build does not prove installer startup, component trust, provider readiness or render reliability.

## Phase handoff checklist

Before handing a phase to the next one:

- [ ] git status --short contains only intentional phase files before commit.
- [ ] git diff --check passes.
- [ ] git diff --cached --name-only contains no secret, upload, model, volume, cache or runtime output.
- [ ] Large-file and secret scans report no unapproved findings.
- [ ] Required development-stack checks were run without changing the Docker localhost implementation.
- [ ] The phase gate, limitations and exact commit hash are recorded.
