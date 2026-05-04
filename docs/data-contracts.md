# Data Contracts

This document captures the current data flow during the SQLite migration. The
goal is to make each cutover explicit so Scout, Matcher, Tailor, and the
dashboard do not break while storage changes underneath.

## Current Sources Of Truth

### Companies

Current company state is split across several files:

- `scripts/ats_scout.py`
  - Contains the hardcoded `COMPANIES` list.
  - Current Scout source of truth.
  - Fields: `name`, `ats`, `slug`, `stage`, `vertical`.
- `scripts/companies_master.txt`
  - Newline-delimited company names.
  - Used as a seed/list source, not by Scout directly.
- `scripts/a16z_companies.txt`
  - Newline-delimited company names for a16z.
- `workspace/all_vc_companies.csv`
  - Getro scrape output.
  - One row per VC/company appearance, so duplicates across VCs are expected.
- `workspace/ats_mapping_779.csv`
  - Ranked Getro-to-ATS mapping output.
  - Contains ATS provider/slug where detected plus fit/source metadata.
- `scripts/bulk_add_results.csv`
  - Checkpoint file for dashboard-driven ATS detection/add flows.

### Jobs

Job state is generated from scans, imported into SQLite, scored in SQLite, and
then projected into dashboard state:

- `workspace/jobapp.db`
  - `job_postings` is the source of truth for jobs.
  - `job_url_aliases` preserves historical `job_url` / `apply_url` keys.
  - `job_scores` is the source of truth for shortlist scores.
  - `job_interactions` is the source of truth for comments, selected,
    reviewed/applied, and manual fit scores.

- `workspace/raw_jobs.json`
  - Written by `scripts/ats_scout.py`.
  - Backup/export artifact for compatibility and debugging.
  - Top-level keys include `scan_date`, `config_version`, `company_stats`,
    `jobs`, and `errors`.
- `workspace/shortlist.json`
  - Written by matcher scripts.
  - Backup/export artifact for compatibility and debugging.
  - Contains `total_scanned`, `total_shortlisted`, and `jobs`.
- Dashboard state files:
  - `feedback.json`: user fit ratings and comments keyed by URL.
  - `job_status.json`: reviewed/applied state keyed by URL.
  - `selected.json`: selected job URLs.
  - `comments.json`: notes keyed by URL, if present.
  - `tailored_resumes.json`: tailored resume file metadata keyed by job URL.

## Current Identity Rules

### Company Identity

Current duplicate checks are inconsistent. They use one of:

- normalized company name
- ATS provider + ATS slug
- raw slug string

SQLite target rule:

- `companies.normalized_name` is unique.
- `ats_endpoints(provider, slug)` is unique.
- A company can have many source rows and one or more ATS endpoints.

### Job Identity

Current dashboard state usually uses `job_url`, but Tailor sometimes receives
and stores `apply_url`. This can cause tailored files not to map cleanly back to
cards.

SQLite target rule:

- Prefer `source + external_job_id`.
- Fall back to `source + job_url`.
- Use URL aliases during migration so old `job_url`/`apply_url` keyed state is
preserved.

## Compatibility Rules During Migration

Normal runtime should use SQLite:

- Scout still writes `workspace/raw_jobs.json` as a backup/export.
- Matcher reads jobs from `job_postings`, writes scores to `job_scores`, and
  exports `workspace/shortlist.json` as a backup/export.
- Dashboard `/api/data` returns the current JSON response shape, but assembles
  it from SQLite when `workspace/jobapp.db` exists.
- Tailor writes `resume_artifacts` and may keep `tailored_resumes.json` as a
  backup/export.
- Existing dashboard state keyed by URLs is preserved through
  `job_url_aliases`.

## Refactor Phases

1. Add SQLite schema and import scripts without changing live behavior.
2. Validate imported counts and duplicate constraints against current files.
3. Change Scout to read active companies from SQLite, while keeping the same
   `raw_jobs.json` output. This is now implemented with legacy fallback:
   `ats_scout.py` loads from `workspace/jobapp.db` when present and falls back
   to the hardcoded `COMPANIES` list if the DB cannot be loaded.
4. Change dashboard company add/delete endpoints to mutate SQLite, not
   `ats_scout.py`. This is now implemented. The dashboard companies table reads
   from SQLite, and add/delete update `companies` and `ats_endpoints`.
5. Move dashboard job state to stable `job_id`, with URL alias fallback. This
   is implemented for normal runtime: dashboard job reads come from SQLite,
   dashboard state writes go to `job_interactions`, and matchers save current
   scores to `job_scores`. Legacy JSON files remain as fallback/export
   artifacts.
6. Remove the hardcoded `COMPANIES` list only after compatibility exports are
   proven.

## Scout Company Source

`scripts/ats_scout.py` now supports two company sources:

- `sqlite`: default when `workspace/jobapp.db` exists and contains Scout rows.
- `legacy`: hardcoded `COMPANIES` fallback.

Set `PP_JOBAPP_COMPANY_SOURCE=legacy` to force the old path during debugging.
Set `PP_JOBAPP_COMPANY_SOURCE=db` to require the SQLite path; if the DB is
missing or invalid, Scout still falls back but prints a warning.

The `raw_jobs.json` contract is intentionally unchanged as an export artifact.
Scout prints the selected company source to stdout. Normal downstream job reads
should use SQLite after running `scripts/migrate_to_db.py`.

## Dashboard Mutations

Dashboard company mutations now use SQLite:

- `/api/add_company/confirm` upserts `companies`, adds a `dashboard_manual`
  source row, and upserts an active `ats_endpoints` row.
- `/api/companies/delete` marks the company inactive and marks its endpoints
  `deleted`; it also removes current jobs for that company from the live
  compatibility JSON files.
- `/api/companies` reads the SQLite Scout company list.

Dashboard job-state mutations now write SQLite when `workspace/jobapp.db`
exists, with legacy JSON fallback only if the DB is unavailable:

- comments/selected/reviewed/applied: `job_interactions`
- manual fit scores: `job_interactions` and `job_scores` with `scorer='manual'`

The matcher feedback loop now reads manual examples from SQLite first and falls
back to `feedback.json` only when the DB is unavailable or empty.

The dashboard scan route runs Scout, Matcher, then `migrate_to_db.py` so newly
generated `raw_jobs.json` / `shortlist.json` records are imported into SQLite
before the scan is marked done.
