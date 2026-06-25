# RAG and Course Material Pipeline

```mermaid
flowchart LR
  F[PDF/PPTX/DOCX/TXT/MD/CSV] --> X[Text extraction]
  X --> P[Page-aware cleaning]
  P --> C[300-token chunks / 50 overlap]
  C --> E[OpenAI-compatible embeddings]
  E --> Q[(Qdrant course_materials)]
  T[Transcript batch] --> S[Top-k semantic search]
  Q --> S
  S --> A2[Agent 2 prompt context]
  F --> IMG[Rendered PDF/PPTX page images]
  IMG --> A4[Agent 4 visual planning]
```

| Parameter | Current value | Evidence |
|---|---|---|
| Collection | `course_materials` | `backend/app/config.py`; `backend/app/rag/vector_store.py:52-64` |
| Embedding | `text-embedding-3-small`, 1536 dimensions | `backend/app/config.py` |
| Chunking | 300 tokens, overlap 50 | `backend/app/config.py` |
| Search | top-k 5, threshold 0.0 default | `backend/app/rag/vector_store.py:422-463` |
| Distance | Cosine | `backend/app/rag/vector_store.py:52-64` |
| Retry | one ingest retry after 2 seconds | `backend/app/rag/vector_store.py:112-130` |

PDF extraction uses PyMuPDF text; PPTX extraction includes shapes, tables, and speaker notes (`backend/app/services/text_extraction.py`). PDF/PPTX pages can also be rendered to images for Agent 4 (`pdf_slides.py`, `pptx_slides.py`). Project assets preserve optional one-based page ranges. Qdrant payloads retain source/page/file metadata.

Important limitations: no reranker was found; threshold 0.0 can admit weak matches; no content-hash deduplication was found; scanned PDFs have no implemented OCR despite an OCR-oriented comment/docstring; deletion removes vectors/files/rows but retention guarantees are not authenticated; Agent 2 uses retrieved text while Agent 4 primarily uses rendered page data and semantic prompts.
