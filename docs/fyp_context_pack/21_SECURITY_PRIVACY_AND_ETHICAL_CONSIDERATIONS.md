# Security, Privacy, and Ethical Considerations

Lecture videos, transcripts, course materials, edit plans, provider traces, and exports are stored in PostgreSQL and configured local filesystem directories; course embeddings are sent to/stored in Qdrant. Hosted ASR, chat, embedding, or vision routes transmit relevant content to third-party providers when configured. whisper.cpp offers a local ASR route, but local chat/vision/embedding routes are placeholders.

The application has no evidenced authentication or role-based authorization. API keys can be encrypted at rest only when `APP_SETTINGS_SECRET_KEY` is configured (`backend/app/services/app_settings.py:210-241`); otherwise persistence is restricted/error-prone rather than safely encrypted by default. Logging and generated evidence may contain lecture content. Deletion paths exist, but complete secure erasure across database, Qdrant, backups, temp files, logs, and provider systems is not proven.

Ethical risks include provider privacy exposure, copyright/ownership of lecture materials, hallucinated importance or page relations, incorrect content removal, bias in speech recognition, and overreliance on automatic edits. Teacher review, conservative lecturer-only handling, warnings, deterministic plans, and evidence exports are risk mitigations, not guarantees.

Safe thesis wording: "The prototype supports local storage and a local ASR option, while configured hosted providers may receive lecture-derived data. Teacher review and traceable artifacts reduce, but do not eliminate, risks from model error. Authentication, formal retention controls, and a complete privacy impact assessment remain future work."
