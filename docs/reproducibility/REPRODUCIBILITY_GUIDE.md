# Thesis Source-Code Reproducibility Guide

This guide defines the source snapshot used by the Final Year Project thesis, the contents of Appendix A, and the procedure for producing the supplementary source archive.

## 1. Freeze the evaluated implementation

Before submission:

1. Confirm that the working tree contains the same implementation used to generate the Chapter 4 evidence.
2. Run the canonical Python tests, frontend build and Rust check.
3. Commit the intended application, tests, configuration and documentation.
4. Tag the commit `fyp-thesis-v1.0`.
5. Generate the source package from that clean tagged commit.

The appendix and supplementary archive must state the full commit hash, tag, archive SHA-256 checksum, generation timestamp and code-count method.

## 2. Appendix A content

Appendix A contains substantial implementation extracts rather than every repository line. Its listings cover:

1. FastAPI application startup.
2. Five-agent pipeline orchestration.
3. Transcription and curriculum-grounded analysis.
4. Semantic visual planning.
5. Edit planning and deterministic warning checks.
6. Persistent Segment and EditPlan records.
7. Teacher override and approval endpoints.
8. Semantic render-plan construction.
9. Final rendering coordination.
10. Representative automated tests.

Chapter 3 should cite the relevant Appendix A listing beside each methodology-level algorithm.

## 3. Supplementary archive

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\generate_thesis_source_package.py
```

The generated directory contains:

- `AIVE_FYP_Source_Code_v1.0.zip`
- `SOURCE_MANIFEST.csv`
- `SOURCE_SUMMARY.json`
- `CHECKSUMS.sha256`

The manifest records each included path, category, language, physical lines, nonblank lines, size and SHA-256 digest.

## 4. Exclusions

The generator excludes:

- `.git`, virtual environments and dependency directories
- `.env` and local credential files
- uploads, outputs, caches, logs and temporary analysis
- generated Tauri schemas/icons and build directories
- binary evaluation media and database dumps

`.env.example` is included because it documents configuration names without exposing secrets.

## 5. Reproduction prerequisites

Record the following in the final appendix or accompanying submission note:

- Windows version and hardware used for evaluation
- Python, Node.js, Rust, Tauri and FFmpeg versions
- PostgreSQL and Qdrant versions
- provider/model identifiers and evaluation dates
- Docker Compose version
- final Git commit and tag

Provider availability, model behaviour and pricing may change. The exact provider/model identifiers used in the evaluation must therefore be preserved with the Chapter 4 evidence.

## 6. Verification commands

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"
npm run build --prefix desktop
cargo check --manifest-path desktop\src-tauri\Cargo.toml
docker compose config --quiet
```

Record command, date, exit code and result in the final verification table.

## 7. Citation wording for Chapter 3

Recommended wording:

> Selected implementation extracts are provided in Appendix A. The complete sanitised source archive corresponding to the evaluated implementation is supplied as a supplementary digital artefact and is identified by its Git commit, release tag and SHA-256 checksum.

Do not leave future-tense promises such as “source code may be placed in an appendix.”
