# tools/audit/

Read-only inspection scripts. Use this directory for tools that report on the
state of the system without modifying it.

Rules:

- Scripts here **must not** write to `workspace/jobapp.db` or any file under
  `workspace/`.
- No `INSERT`, `UPDATE`, `DELETE`, or schema migrations. Open SQLite
  connections in read-only mode where practical.
- No edits to files under `scripts/`, `resumes/`, or any other tracked path.
- Output goes to stdout (or a path the caller passes explicitly). Do not
  drop new files into the repo as a side effect.
- Same import rule as `tools/`: production code must not depend on anything
  under `tools/audit/`.
