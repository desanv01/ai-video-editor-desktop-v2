# Evaluation Readiness and Measurement

The current application can derive recommendations, overrides, action distribution, visual decisions, uncertain/lecturer-only decisions, provider traces, and render/artifact outcomes. It cannot reliably measure active manual editing time or active teacher review time without an external timer or code changes. Correct slide selection and content preservation require a defined human ground truth/rubric.

The supervisor-approved five-video paired design is feasible using `FIVE_VIDEO_DATA_COLLECTION_TEMPLATE.csv`. Each video must be edited manually and through the agent-assisted workflow, with condition order counterbalanced where possible. Machine processing, active teacher time, render time, and total elapsed time must be separated. Report per-video values and descriptive paired differences; do not claim population significance from five cases.

See `EVALUATION_PROCEDURE.md`, `EVALUATION_RISKS.md`, `EVALUATION_METRIC_MATRIX.md`, and `CHAPTER4_RESULTS_TABLE_TEMPLATE.md`.
