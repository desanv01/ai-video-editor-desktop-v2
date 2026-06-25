# Figure Recreation Specifications

## Figure 1: Project-first teacher-supervised workflow

**Purpose:** Recreate project-first teacher-supervised workflow from verified implementation.
**Verified flow:** Project -> sources -> agents -> review -> render/export.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Project-first teacher-supervised workflow derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Project-first teacher-supervised workflow]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: Project and teacher review loop.


## Figure 2: Detailed multi-agent processing pipeline

**Purpose:** Recreate detailed multi-agent processing pipeline from verified implementation.
**Verified flow:** Agent 1 -> Agent 2 -> Agents 3/4 parallel -> Agent 5.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Detailed multi-agent processing pipeline derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Detailed multi-agent processing pipeline]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: Specialised modules, not autonomous negotiation.


## Figure 3: Current three-tier system architecture

**Purpose:** Recreate current three-tier system architecture from verified implementation.
**Verified flow:** React/Tauri -> FastAPI -> persistence/providers/rendering.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Current three-tier system architecture derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Current three-tier system architecture]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: Redis/MCP shown as non-core.


## Figure 4: Five-agent execution and review pipeline

**Purpose:** Recreate five-agent execution and review pipeline from verified implementation.
**Verified flow:** Agent outputs -> deterministic checks -> teacher overrides.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Five-agent execution and review pipeline derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Five-agent execution and review pipeline]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: Persisted review state.


## Figure 5: Current database/entity model

**Purpose:** Recreate current database/entity model from verified implementation.
**Verified flow:** Nine ORM entities and Qdrant/file side stores.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Current database/entity model derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Current database/entity model]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: Relational versus external persistence.


## Figure 6: Batch-level RAG analysis pipeline

**Purpose:** Recreate batch-level rag analysis pipeline from verified implementation.
**Verified flow:** Material chunks -> embeddings -> Qdrant -> Agent 2 batches.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Batch-level RAG analysis pipeline derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Batch-level RAG analysis pipeline]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: top-k 5, no reranker.


## Figure 7: Semantic visual-planning and slide-relevance flow

**Purpose:** Recreate semantic visual-planning and slide-relevance flow from verified implementation.
**Verified flow:** related/unrelated/uncertain -> layout/review.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Semantic visual-planning and slide-relevance flow derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Semantic visual-planning and slide-relevance flow]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: safe lecturer-only fallback.


## Figure 8: Warning-based edit planning and teacher-override flow

**Purpose:** Recreate warning-based edit planning and teacher-override flow from verified implementation.
**Verified flow:** LLM actions -> validators -> warnings -> teacher.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Warning-based edit planning and teacher-override flow derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Warning-based edit planning and teacher-override flow]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: manual precedence.


## Figure 9: Semantic rendering and evidence-export pipeline

**Purpose:** Recreate semantic rendering and evidence-export pipeline from verified implementation.
**Verified flow:** render plan -> FFmpeg -> verification -> artifacts.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Semantic rendering and evidence-export pipeline derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Semantic rendering and evidence-export pipeline]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: native default, Revideo optional.


## Figure 10: Five-video manual-versus-agent evaluation protocol

**Purpose:** Recreate five-video manual-versus-agent evaluation protocol from verified implementation.
**Verified flow:** paired conditions -> separate timers -> descriptive comparison.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "Five-video manual-versus-agent evaluation protocol derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[Five-video manual-versus-agent evaluation protocol]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: no population inference.

## Verified Mermaid Set

Use these implementation-specific diagrams instead of the generic construction skeletons above.

### Figure 1 verified layout
```mermaid
flowchart LR
  T[Lecturer] --> P[Create or open project] --> S[Add recordings and course materials] --> A[Run AI-assisted pipeline] --> R[Review transcript, sections, visuals and edits]
  R -->|teacher override| R
  R --> E[Approve render and export] --> O[Media, subtitles, chapters and evidence]
```

### Figure 2 verified layout
```mermaid
flowchart LR
  V[Video/audio] --> A1[Agent 1: transcription] --> A2[Agent 2: curriculum-grounded content]
  A2 --> A3[Agent 3: fluency]
  A2 --> A4[Agent 4: semantic visual planning]
  A3 --> A5[Agent 5: edit planning]
  A4 --> A5 --> D[Deterministic validation] --> T[Teacher review]
```

### Figure 3 verified layout
```mermaid
flowchart TB
  TAURI[Tauri 2] --> UI[React 19] --> API[FastAPI]
  API --> ORCH[Async Python orchestrator]
  API --> RENDER[FFmpeg and FFprobe]
  API --> PG[(PostgreSQL)]
  ORCH --> Q[(Qdrant)]
  API --> FS[Filesystem]
  REDIS[Redis] -. configured only .-> API
  MCP[MCP stdio servers] -. optional integration .-> API
```

### Figure 4 verified layout
```mermaid
flowchart TD
  AO[Automatic outputs] --> C[Coherence and consequence checks] --> W{Warnings or uncertainty?}
  W -->|yes| TR[Teacher review required]
  W -->|no| TR[Teacher review available]
  TR -->|accept or override| FP[Final persisted plan] --> RP[Deterministic render plan]
```

### Figure 5 verified layout
```mermaid
erDiagram
  PROJECT ||--o{ PROJECT_ASSET : owns
  PROJECT ||--o{ VIDEO : contains
  VIDEO ||--o| TRANSCRIPT : has
  VIDEO ||--o{ SEGMENT : contains
  VIDEO ||--o{ SCENE : contains
  VIDEO ||--o| EDIT_PLAN : has
  COURSE_MATERIAL ||--o{ QDRANT_CHUNK : embedded_as
  APP_AI_SETTINGS ||--|| APPLICATION : configures
```

### Figure 6 verified layout
```mermaid
flowchart LR
  DOC[Course material] --> X[Page-aware extraction] --> CH[300-token chunks, 50 overlap] --> EM[1536-dimensional embeddings] --> Q[(Qdrant course_materials)]
  B[Agent 2 transcript batch] --> QUERY[Semantic query] --> Q
  Q -->|top-k 5| CTX[Retrieved context] --> A2[Agent 2 structured analysis]
```

### Figure 7 verified layout
```mermaid
flowchart TD
  TW[Transcript window] --> CP[Candidate page shortlist] --> REL{Relation}
  REL -->|related| PAGE[Keep page] --> LAY{PIP, side-by-side or full-source}
  REL -->|unrelated| LECT[Lecturer-only]
  REL -->|uncertain| WARN[Lecturer-only plus review]
  CP -. provider failure .-> LOCAL[Local matching] -. fallback .-> PSD[PySceneDetect]
```

### Figure 8 verified layout
```mermaid
flowchart LR
  I[Agents 2, 3 and 4] --> A5[Agent 5] --> ACT[KEEP, CUT, SHORTEN or HIGHLIGHT] --> VAL[Coherence and removal checks] --> T[Teacher]
  T -->|accept or override plus note| SAVE[Persist final action] --> MET[Override metrics]
```

### Figure 9 verified layout
```mermaid
flowchart LR
  AP[Approved plan] --> SRP[Semantic render plan] --> JOB[Persistent render job] --> FF[Native FFmpeg compositor] --> CHECK[FFprobe verification]
  JOB -. optional .-> REV[Revideo]
  CHECK --> VIDEO[MP4 or M4A]
  CHECK --> SUB[SRT and VTT]
  CHECK --> CHAP[Chapters]
  CHECK --> EVID[Plan, metrics and evidence]
```

### Figure 10 verified layout
```mermaid
flowchart TD
  FIVE[Five videos] --> ORDER[Counterbalanced order]
  ORDER --> MAN[Manual edit and active timer]
  ORDER --> AG[Agent-assisted edit]
  AG --> MACH[Machine time]
  AG --> REV[Teacher active time]
  AG --> REN[Render time]
  MAN --> PAIR[Paired per-video record]
  MACH --> PAIR
  REV --> PAIR
  REN --> PAIR --> DESC[Descriptive comparison and failure analysis]
```
