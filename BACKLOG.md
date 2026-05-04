# pp-jobapp backlog

Single source of truth for engineering work. Priorities re-ranked 2026-05-04.

Tiers reflect urgency, not effort. "Do soon" doesn't mean small.

> For backward-looking history (refactors, migrations, data operations),
> see [CHANGELOG.md](./CHANGELOG.md).

---

## Tier 1 — Critical (next 2 weeks)

### 1. Consolidate matcher scripts
`ats_scout_getro_match_new.py` was a one-off Getro-batch variant; its
delta-scoring behavior is genuinely useful (re-scoring all jobs is
wasteful at $0.002/job). Fold delta-scoring into `ats_matcher.py` —
skip jobs with recent `job_scores` entries — and archive the variant.
After consolidation, canonical pipeline is `ats_scout.py` →
`ats_matcher.py`, both invokable via dashboard /api/scan or directly.
**Why now:** cost compounds with every backfill, and the duplication
creates two sources of truth (job_scores DB vs shortlist.json file).

### 2. URL enrichment for missing-website-URL companies
~1,000 companies in DB have no `website_url`, ineligible for
website-based ATS probing. Build `enrich_website_urls()` in storage.py:
for each company without URL, try `https://{normalized_name}.{com,ai,io,co}`,
validate with HEAD request (5s timeout, follow redirects), populate column.
Then re-run `discover_phase()` on these companies.
**Yield estimate:** 200-400 additional ATS endpoints.

### 3. Daily pipeline cron
No crontab exists today. After backfill produces 1,400-2,000 endpoints,
running scout+matcher daily becomes worth automating. Set up:
`0 6 * * * cd /root/pp-jobapp && python3 scripts/ats_scout.py && python3 scripts/ats_matcher.py >> workspace/cron.log 2>&1`
(Schedule + path adjusted to taste.)

## Tier 2 — High value (2-4 weeks)

### 4. Workday provider support
Cityblock Health was probing as Workday in May 2026 audit. Workday URL
patterns already in detection regex; need `fetch_workday()` in
ats_scout.py (POST with JSON body, different shape from Ashby/GH/Lever).
Endpoints respond at `{tenant}.wd1.myworkdayjobs.com/{site}/jobs`.
**Yield estimate:** 200+ endpoints.

### 5. Twin / alias consolidation
Companies appearing under multiple normalized_names representing same
real-world entity (cohere/coheretechnologies, mistral/mistralai,
n8n/n8nio). Backfill attaches endpoints to whichever twin processes
first; orphan remains. Build consolidation tool: detect twins via
slug collision in ats_endpoints, merge — re-attribute company_sources,
mark one inactive, preserve provenance.
**Note:** This subsumes the README Roadmap "company alias/merge layer"
item — they describe the same work.

### 6. applied_history.json
Surface "you already applied here" signal in fresh scans to prevent
double-applying. Small task, high personal utility.

## Tier 3 — Defer until measured signal (4+ weeks)

### 7. Long-tail ATS providers
Bullhorn, Recruiterflow, Eightfold, Phenom, iCIMS, Cornerstone, Taleo,
SuccessFactors, JobScore, Breezy. Don't speculatively add all —
after backfill, look at miss patterns and add only providers that
appear ≥5 times.

### 8. JS-rendered careers page support
Some companies (e.g., Anduril) embed slug only at runtime via JS;
static HTML mentions provider but slug fetched async. Two options:
lightweight (when probe sees `greenhouse.io` mention but no slug match,
retry candidate generator against Greenhouse API) or heavyweight
(Playwright render). Decide after measuring how many companies remain
in this bucket.

### 9. Job-posting dedup audit
Same role appearing through multiple sources/URLs gets deduped via
`job_url_aliases` today. Verify coverage; extend if gaps. Investigation
task, not implementation.

### 10. Scheduled re-discovery cron
Weekly cron of `discover_phase()` so companies that switch ATS providers
eventually get re-detected. `max_age_days` parameter already supports
this. Most value captured by one-time backfill; this catches drift over
time.

## Tier 4 — Strategic (requires solid foundation first)

### 11. 5K company expansion
Original goal that started this whole effort. Premature until ATS
detection catches up. Reconsider once active endpoints ≥ 2,500.
Sources identified: 899 Getro VCs at community.getro.com, tier-2 VCs
(645 Ventures, 8VC, BCV, Battery, CRV, Emergence, Felicis, FirstMark,
Foundation, IVP, Lerer Hippeau, Lux, Mayfield, Menlo, Norwest, Redpoint,
Spark, Threshold, Union Square, Upfront), YC Work at a Startup
(~1,000 cos), Tiger/Insight/Founders Fund/Coatue/Thrive/Index (custom
scraping required).

### 12. SEC Form D scraper integration
`edgar_formd_scraper.py` exists as sibling experiment. Promote into
daily pipeline as "newly-funded" sourcing signal once #11 is active.

### 13. Browser agent for assisted form-filling
Largest item; separate workstream. Don't scope until everything above
is in flight.

## Cleanup (do during related work)

### 14. Remove legacy hardcoded COMPANIES fallback
SQLite-backed paths are now default. Remove the in-script `COMPANIES`
list and `PP_JOBAPP_COMPANY_SOURCE=legacy` escape hatch from
`ats_scout.py` during the next session that touches it.

