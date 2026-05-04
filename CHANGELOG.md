# Changelog

Curated record of meaningful system changes. For mechanical commit history,
see `git log`.

An entry belongs here if a future contributor (human or AI agent) would
benefit from knowing about it weeks or months later — refactors, migrations,
data operations, architectural decisions. Bug fixes and small features stay
in git log only.

Reverse-chronological. Most recent first.

---

## 2026-05-04 — ATS detection refactor + first backfill

Major detection-logic overhaul plus the first DB-wide backfill of
`ats_endpoints`.

- Extracted `detect_ats()` from dashboard.py to storage.py as a pure,
  importable function. Dashboard route became a thin wrapper.
- Added `discover_phase()` to ats_scout.py — orchestrates discovery
  across the DB, writes hits/misses/dead URLs to `ats_endpoints` with
  `last_checked_at` so runs are resumable. New CLI flags
  `--discover`, `--then-scan`, `--limit`, `--max-age-days`.
- Detection logic improved: ~60 candidate slugs (suffix variants,
  prefixes, suffix-stripping, domain-stem); 15 careers-page paths
  probed; 12 ATS signature patterns; DNS pre-flight detects dead URLs
  early; URL-decoding + case preservation in slug capture; empty-jobs
  response now treated as a hit.
- Bulk scripts (`bulk_add_companies.py`,
  `ats_scout_getro_bulk_add.py`) now call `storage.detect_ats()`
  directly — removed the localhost:5000 HTTP dependency on the
  dashboard process being up.
- Reactivated 2,402 companies that had been bulk-deactivated by the
  old detection's no-ATS failures (verified none were
  `dashboard_manual` deletions before reactivation).
- Launched first backfill of `discover_phase()` across all 2,402
  reactivated companies via `tools/backfill_ats_detection.py`.

Commits: 88aeb7d, eae0863, 0a0db14, 6738d32, 791a97b, fe548d8, 48120cf

## 2026-05-04 — Repo hygiene: tools/ and archive/ structure

- Introduced `tools/` for one-off human-run scripts (with
  `tools/audit/` carrying read-only inspection tools), and `archive/`
  for deprecated code kept for historical reference. Updated
  `.gitignore` for `__pycache__`/scratch files.
- Added `__main__` guard to `ats_scout.py` to prevent the
  import-runs-the-scan footgun that bit us this same session.

Commits: c57cc94, ffe39a0

## 2026-05-04 — SQLite Phase 5: dashboard + matcher DB-native

Dashboard, matcher, and scout flipped from JSON to SQLite-canonical
reads.

- Dashboard `/api/data` and company scan stats now read from SQLite
  (`job_postings` + `job_scores`) instead of `raw_jobs.json`.
- Matchers load jobs from SQLite, write scores to `job_scores` under
  `scorer='current_shortlist'`. `shortlist.json` becomes
  backup/debug only.
- Dashboard scan order: Scout → migrate/import to DB → Matcher, so
  the Matcher sees fresh scanned jobs through SQLite.
- `raw_jobs.json` and `shortlist.json` retained as backup exports,
  not read in normal operation.

Commits (approx): 9459a02, 791d71b, e90dfc8, 86e04d3, 46948c1, e94a66d

## 2026-05-03 — sqlite-phase-5-db-native PR merged

Umbrella PR landing the SQLite migration. Removed JSON fallback paths;
system now fails loudly when DB missing rather than silently falling
back. Untracked OpenClaw agent identity files (`USER.md`, `AGENTS.md`,
etc) — they remain as templates in repo but per-instance state is
gitignored.

Commits: 55dff8e, bda367b

## 2026-05-02 (Session 7) — Getro VC sourcing + bulk-add + Sonnet upgrade

- First production `getro_scraper.py`.
- 779-VC bulk scan via `ats_scout_getro_bulk_add.py` +
  `bulk_add_companies.py`.
- Resume library expanded.
- Tailor model: Sonnet 4 (2025-05-14) → Sonnet 4.6.
- WhatsApp integration removed.
- Project renamed; README simplified.

Commits: 52d7fdd, 17de298, 3cc2396, 2a441c7, ca9dedf, ddc4d9c, ef6d168, ab55750

## 2026-04-09 — Dashboard review-panel hotfixes

Two specific footguns worth recording so they don't get reintroduced:

- onclick truncation from `&` in role titles → fixed via data
  attributes (don't inline-string-concat role titles into onclick
  handlers).
- Education header conflict in tailored docx → fixed; consolidated
  known issues; updated session history.

Commits: 4a9c38c, 7f60303

## 2026-04-08 (Session 4) — Resume library + dashboard review panel

Curated library of 12 prior tailored versions wired into `tailor.py`
as context. Master resume updates, PDF fixes, dashboard review panel.

Commits: c64d91d

## 2026-04-08 (Session 3) — Resume Tailor + PDF generator + posting dates

Tailor (Claude Sonnet) introduced. PDF generator (WeasyPrint Clean
Classic, auto 1-page). Posting dates surfaced in dashboard with
freshness coloring.

Commits: 8aadc80

## 2026-04-07 (Sessions 1-2) — Initial pipeline

ATS Scout (Ashby/Greenhouse/Lever direct JSON APIs). DeepSeek scoring
matcher. Flask dashboard with job cards, comments, quick tags. Skill
files, `docs/` structure. WhatsApp message generation (later removed
in Session 7). `workspace/` excluded from git (managed by OpenClaw
harness).

Commits: 5697ef5, 32c2f52, 5788269, d345353, faa05d7, 686d432

## 2026-04-07 — Architecture: ATS direct API over Playwright

Foundational decision: skip browser automation, hit Ashby /
Greenhouse / Lever JSON APIs directly. Rationale documented in
`CAREER_OPS_LEARNINGS.md`. No browser dependency in the production
pipeline.
