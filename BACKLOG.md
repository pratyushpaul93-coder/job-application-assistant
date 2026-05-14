# pp-jobapp backlog

Single source of truth for engineering work. Priorities re-ranked 2026-05-08
based on findings in `docs/investigations/2026-05-07_phase2_unknown_audit.md`
(see Addendum 2026-05-08 for the JS-rendering yield correction).

Tiers reflect urgency, not effort. "Do soon" doesn't mean small.
Within each tier, items are ordered by yield toward the 2,000-matched-jobs
goal (largest first), with effort tags for sequencing.

> **Strategic note (2026-05-08):** The 2,000-match goal no longer closes
> from the existing 3,169-company population alone. Workday shipped
> 2026-05-08 (+27 endpoints, ~5,200 jobs); detector bug fixes (#1) and
> long-tail providers (#4) together add a further ~+495 matches. Even
> at the upper bound, in-population work tops out around ~1,300-1,500
> matches. Closing the gap requires bringing forward Tier 4 sourcing
> items (5K expansion, Form D) or finding a new SPA-recovery technique.
> See investigation addendum.

> For backward-looking history (refactors, migrations, data operations),
> see [CHANGELOG.md](./CHANGELOG.md). For investigations behind backlog
> decisions, see [docs/investigations/](./docs/investigations/).

---

## Tier 1 — Critical (next 2 weeks)

### 1. Detector bug fixes (Phase 2 audit findings)
**Yield:** +64 endpoints → ~+422 matched. **Effort:** Low — extending an
existing system additively, ~1-2 days.

**Update 2026-05-12:** Adjacent improvement landed first: full browser-mimic
headers in `_http_get_text` (CHANGELOG 2026-05-12). On partial Fortune
redetect (150/786 done), already recovered Concentrix, Caterpillar,
Stanley Black & Decker, LKQ, Prudential, Mastercard — all Workday tenants
the regex was already matching but couldn't reach because their /careers
pages 403'd bare UA. Final headers-fix yield: 56 hits (mostly Workday).
The audit-identified Workable / bamboohr / teamtailor slug-probe gaps
below remain unfixed.

**Update 2026-05-13:** 7 enterprise ATS detectors shipped — Eightfold,
Avature, Brassring, iCIMS, Phenom, Taleo, Oracle HCM (see CHANGELOG
2026-05-13). Verified against 11 known Fortune cos (Walmart, Starbucks,
Citi, NGC, Morgan Stanley, CBRE, Lockheed, Delta, Walgreens, Publix,
Dollar General — all detect correctly). Fortune redetect-v2 in progress
against 731 failures; expected ~240 additional hits from yesterday's
audit extrapolation. The Workable / bamboohr / teamtailor gaps remain
the last items on this list.

Four concrete failure modes in `scripts/storage.py` that account for **64
companies** in the unknown bucket whose ATS exists and is live, but the current
detector misses them. Highest yield-per-effort of any backlog item.

Sub-fixes (all touch `_ATS_SIGNATURES` and/or `_try_slug_candidates`):

- **Greenhouse `embed/job_board/js?for=...` regex variant** — add the missing
  pattern to `_ATS_SIGNATURES`. Recovers 8 companies (Housecall Pro,
  LightForce, Relativity Space, Vectra, Density, Noom, …).
- **Workable in slug-candidate probing** — currently only Ashby/GH/Lever are
  probed; Workable falls through to website-probe-only. Recovers 15
  (Marqo, Carry1st, Bettermode, YouTrip, Portainer, …).
- **bamboohr in slug-candidate probing** — same gap. Recovers 8
  (Prezi, ZAGENO, Anaqua, Shortcut, …).
- **teamtailor in slug-candidate probing** — same gap. Recovers 5
  (PredictHQ, Nym, Tractive, Factorial).
- **Ashby URL-encoded multi-word slug variants** — slug-candidate gen needs
  to try `Citizen%20Health`-style variants. Recovers ~14
  (Citizen Health, Tools for Humanity, Nautilus Biotechnology, …).
- Other (lever, jazzhr, smartrecruiters miscellany) — ~14 across the long tail.

**Reference:** `docs/investigations/2026-05-07_phase2_unknown_audit.md`.
**Re-validation after fix:** rerun `tools/phase2_unknown_audit.py`; the
`missed_by_discover` count should drop sharply.

### 1b. Slug-similarity check in `detect_ats` — prevention
**Yield:** 0 endpoints (correctness). **Effort:** Low — single helper +
post-validation step, ~half day.

Today's Fortune redetect surfaced two classes of "right ATS, wrong company"
false positives:
- **Discover Financial Services → workday/capitalone:wd12:Capital_One** —
  Discover's careers page mentioned Capital One; the regex captured Capital
  One's legitimate Workday URL and assigned it to Discover.
- **Medallia → lever/dnb** — Medallia linked to a D&B job listing; D&B's
  Lever slug `dnb` was attributed to Medallia.

Both were caught manually and deleted, but the class persists silently
until audit. Fix: after `_validate_captured_slug` returns a hit, compare
the captured slug to `normalize_name(company_name)` — if they don't share
a 3+ char overlap, log + reject (or downgrade to `status='suspect'`).

Edge: legitimate cross-cos like Berkshire Hathaway → GEICO slug. Allow
opt-out via allowlist or via the website-domain check (if captured slug's
implied URL matches the company's known website host, accept).

### 1c. Phenom + Oracle HCM audit — validate detectors against real Fortune cos
**Yield:** Likely +10-30 endpoints if hits exist; otherwise deprecate
regexes. **Effort:** Low — manual probe of 20-30 known suspects, ~2 hours.

Both detectors shipped 2026-05-13 (CHANGELOG entry same date) but Fortune
redetect-v2 surfaced 0 hits for each. Two possibilities:
1. The 80-co sample (2026-05-12 audit) overestimated their prevalence.
2. Their careers pages are JS-rendered such that the static-HTML signature
   doesn't appear (similar to Walmart's Eightfold case before we added the
   slug-candidate fallback).

Investigation:
- Sample 20-30 Fortune cos with HQ-style careers pages (Tyson Foods,
  GE Vernova, GM, Disney, Sherwin-Williams, etc.) and probe their careers
  URLs directly for `phenompeople.com` / `.oraclecloud.com/...` strings.
- If hits exist, add Phenom + Oracle HCM to `_try_slug_candidates`
  fallback (same pattern as Eightfold/Avature got today).
- If no hits, deprecate the regex and remove from `ATS_PROVIDERS_DETECTABLE`.

### 1d. Make Eightfold / Avature / iCIMS / Brassring / Taleo scannable
**Yield:** ~130 Fortune cos × avg ~200 open jobs each = 25K+ jobs added to
matcher rotation. **Effort:** revised 2026-05-13 — see findings below.

Today's detector work added 129 Fortune endpoints under these 5 providers
but none are in `ATS_PROVIDERS_SCANNABLE`, so `ats_scout` doesn't fetch
jobs from them. They show up in dashboard counts but don't contribute
to job matches.

**Direct-API path is harder than expected** (probed 2026-05-13):
1. **Eightfold** — `/api/apply/v2/jobs` returns 403 "Not authorized for PCSX"
   without a session token its JS app obtains via a handshake.
2. **iCIMS** — Customer API requires a per-tenant Customer ID + auth.
   Public listing pages (`careers-<co>.icims.com/jobs/search`) are SPAs;
   no JSON-LD in static HTML.
3. **Avature, Brassring, Taleo** — same SPA / session-bound pattern.

So the simple-HTTP-fetcher approach (like Workday's) won't work for any
of these 5. Three realistic paths instead — pick one as Phase 1e (next).

### 1e. SerpAPI Google Jobs as the universal fetcher (preferred path for 1d)
**Yield:** Same ~25K+ jobs as 1d. Plus catches the ~360 custom-platform
Fortune giants (Walmart's jobs.walmart.com, Amazon's amazon.jobs,
Microsoft's careers.microsoft.com, etc.) that we can't even detect today.
**Effort:** Low — 1 integration covers everything. ~1 day backend + UI.

**Cost shape:** SerpAPI Google Jobs engine. Naive daily-scan-all = ~$150/mo
Production tier. With cost-minimization architecture, target ~$0/month
steady-state (free tier: 100 queries/month).

**Cost-minimization architecture (validated 2026-05-13 with user):**
1. **Manual trigger only** — zero auto-scan, zero accidental cost. User
   clicks "Scan via SerpAPI" on a starred company.
2. **Keyword-scoped queries** — `q="<co>" "forward deployed"` etc.
   Google Jobs returns only matching jobs, no pagination needed. ~6 queries
   per co per scan vs ~10+ paginated.
3. **7-day per-(co, query) result cache** in `serpapi_cache` SQLite table.
   Re-running scan within 7 days = free (cache hit). Aligns with the 14-day
   `MAX_JOB_AGE_DAYS` recency filter.
4. **Hard daily query budget cap** — env var `SERPAPI_DAILY_QUERY_BUDGET=50`.
   Scan logs + skips when exceeded.
5. **User-marked priority flag** — new `companies.serpapi_priority`
   column; only flagged cos appear in the "Scan via SerpAPI" UI surface.

**Build steps:**
1. SerpAPI signup + API key → `/root/.serpapi/key` (mode 0600)
2. `keys.get_serpapi_key()` (mirror of `get_tavily_key`)
3. Schema migration via `_ensure_columns`: `companies.serpapi_priority INTEGER`
   + `serpapi_cache` table
4. `scripts/serpapi_scout.py` — `fetch_jobs_via_serpapi(co, keywords)` with
   cache, budget tracking, and evaluate_role filtering
5. `/api/scan_via_serpapi` Flask route + a CLI fallback for testing
6. Dashboard UI: priority-toggle button on company cards + "Scan via
   SerpAPI" button visible only on priority cos
7. Validate against Walmart (Eightfold) and Dollar General (iCIMS) before
   committing UI changes

**Why preferred over per-provider reverse-engineering or Playwright:**
- One integration replaces 5+ fetchers
- Catches the ~360 custom-platform Fortune giants for free (same query
  works for `jobs.walmart.com` as for `walmart.eightfold.ai`)
- Free-tier compatible for casual exploration; ~$75/mo Developer tier
  covers heavy use
- Less maintenance than per-tenant scrapers

**Alternative considered:** Tavily site:-scoped queries (we already have a
key). Cheaper but less structured (no posted_date in results). Reasonable
fallback if SerpAPI cost proves unjustified.

## Tier 2 — High value (2-4 weeks)

### 2. URL enrichment cost discipline + cache-age gating
**Yield:** 0 endpoints (prevention). **Effort:** Low — config + cache-age gate
+ spend counter, ~half day.

**Incident 2026-05-04:** Tier-2 retry (`tools/retry_tier2_failures.py`,
671 companies via Claude Haiku + `web_search_20250305`) burned ~$13 in
one run; cumulative recent enrichment spend ~$25+, fully drained the
Anthropic balance and broke `tailor.py` until topped up. Web search
tool is priced at $10 / 1,000 searches → ~$0.02 per company at
`max_uses=2`, which dominates Haiku token cost.
**Bundle three changes:**
- **Cache-age gating on retry:** skip companies enriched within last N
  days unless `--force`. Today's "comprehensive" mode re-hits every
  unverified row regardless of recency.
- **Confidence-threshold gating:** don't retry rows already at
  medium+ confidence with a valid `head_status`.
- **Search budget / backend:** drop `max_uses` from 2 → 1, or swap to
  a cheaper search backend (Tavily/Serper) and have the model parse
  results (token-only cost). Switching Anthropic models *alone* won't
  help — cost is dominated by the search tool, not tokens.
**Also add:** running spend counter in the script so future passes are
visible mid-run, not as a post-hoc surprise.

**Update 2026-05-13:** The outreach drafter (CHANGELOG 2026-05-13) shipped
its own daily-cap gate (`outreach/budget.py`, default `OUTREACH_DAILY_CAP_USD=5`)
that sums cost across `outreach_drafts.cost_usd` and `outreach_research_cache.cost_usd`
and refuses calls past the cap (HTTP 429). The pattern is good — port the same
shape to URL enrichment when fixing this item: a thin `budget.py` per consumer,
spend tracked in the call site's own table, daily aggregation by `substr(created_at, 1, 10)`.

### 2c. Outreach follow-up reminders
**Yield:** lifts response rate on cold outreach — industry data suggests
a polite second touch typically doubles reply rate. **Effort:** Low —
new dashboard surface + a follow-up slant in `kit.yaml`, ~half day.

The schema is already there: `outreach_drafts.sent_at` is populated when
a variant is marked sent, `outreach_drafts.outcome` is `NULL` until tagged.
A draft is a follow-up candidate if:
- `status = 'sent'` AND
- `outcome IS NULL` (no response yet, or untagged) AND
- `sent_at` is 5-7+ days old AND
- no newer sent draft exists for the same `job_id` (so we don't nudge twice).

What to build:
- New dashboard surface — likely a "Follow-ups due" section on the pipeline
  tab, or a counter badge on the existing card "Outreach (N)" button when
  a follow-up is overdue. List shows job, company, days-since-sent, the
  subject of the original message, one-click "Draft follow-up".
- New slant in `outreach/kit.yaml` — `follow_up`:
  - Short (target ~60-80 words, half the length of an initial outreach).
  - Opens with a reference to the prior message ("Following up on my note
    from last week — wanted to ask if there's a fit for a 15-min chat").
  - Drops the about-me bio entirely (recipient already saw it).
  - Either reinforces ONE specific company hook from the original, or
    adds a fresh signal (recent news, product launch, mutual connection).
- A `follow_up_to` (INTEGER, nullable, FK to `outreach_drafts.id`) column
  so the lineage is explicit and the patterns view (#2b) can later
  distinguish first-touch reply rate from follow-up reply rate.
- Configurable reminder window (default 6 days; user can tune in env).

Useful pairing: once #2b ships, the priors view can surface "follow-up
slant has X% response rate vs first-touch Y%" — gives Pratyush real
feedback on whether follow-ups are worth the time.

### 2b. Outreach patterns view + Bayesian priors generator (deferred)
**Yield:** improves draft quality over time. **Effort:** Low — pure SQL +
diff computation, no new infra. Defer until 10+ sent drafts with tagged
outcomes have accumulated, otherwise the patterns table is noise.

The drafter already reads `workspace/outreach_priors.txt` into its system
prompt if present (see `_load_priors()` in `outreach/drafter.py`). This item
is just the generator + the dashboard tab that surfaces patterns.

What to build:
- New dashboard tab "Outreach patterns" — three tables:
  1. **Phrases you keep deleting** — diff `original_body` vs `body` on
     edited drafts; top phrases by frequency across ≥3 drafts.
  2. **Phrases you keep adding** — same diff, in the additions direction.
  3. **Slant performance** — for sent drafts with `outcome` tagged,
     response rate per slant + per (slant × company-vertical).
- Generator: nightly batch (or compute-on-open) that writes
  `workspace/outreach_priors.txt` as 3-5 short bullets the drafter then
  injects verbatim. Threshold: a phrase only enters the priors after
  appearing in ≥3 different drafts (denoise idiosyncratic edits).
- Outcome categories are currently binary (`response` / `no_response`)
  by user request — granular categories can be added later if signal
  warrants.

## Tier 3 — Defer until measured signal (4+ weeks)

### 3. Twin / alias consolidation — demoted from T2 on 2026-05-08
**Yield:** ~0 endpoints (the canonical twin already has them). **Effort:**
Medium — detect + merge + preserve provenance, ~1 day.

Companies appearing under multiple normalized_names representing same
real-world entity (cohere/coheretechnologies, mistral/mistralai,
n8n/n8nio). Backfill attaches endpoints to whichever twin processes
first; orphan remains. Build consolidation tool: detect twins via
slug collision in ats_endpoints, merge — re-attribute company_sources,
mark one inactive, preserve provenance.
**Note:** Subsumes the README Roadmap "company alias/merge layer" item.
**Demoted because:** zero yield toward the 2K goal; pure data hygiene. Defer
until something forces it (e.g., dashboard duplicate clutter becomes annoying).

### 4. Long-tail ATS providers — narrowed by audit data
Threshold for adding a provider: ≥5 occurrences in the unknown bucket. Per
the 2026-05-07 audit, only **iCIMS (6)** and **Eightfold (5)** clear it.

- **Add:** iCIMS, Eightfold (when this item gets picked up).
- **Defer / don't add yet:** Breezy (4), SuccessFactors (3), Phenom (2),
  Jobscore (2), Cornerstone (1), Recruiterflow (1), Bullhorn (0), Taleo (0).

Combined yield from iCIMS + Eightfold: +11 endpoints. Implementation
pattern matches the just-shipped Workday work (new regex + new
fetcher + slug strategy) — the storage.py changes from 2026-05-08
provide a template.
**Reference:** `docs/investigations/2026-05-07_phase2_unknown_audit.md`.

### 5. Job-posting dedup audit
Same role appearing through multiple sources/URLs gets deduped via
`job_url_aliases` today. Verify coverage; extend if gaps. Investigation
task, not implementation.

### 6. Scheduled re-discovery cron
Weekly cron of `discover_phase()` so companies that switch ATS providers
eventually get re-detected. `max_age_days` parameter already supports this.
**NOTE 2026-05-06:** project preference is manual-trigger only; reframe as a
manual `discover_phase()` re-run cadence, not a cron, or drop entirely.

### 7. Consolidate matcher scripts
`ats_scout_getro_match_new.py` is a one-off Getro-batch variant.
**Demoted from Tier 1 on 2026-05-06**: `ats_matcher.py` already has
rubric-keyed cache check at `scripts/ats_matcher.py:645-653`, so cost
is already bounded. The 2026-05-05 run scored 2,009 jobs and only hit
DeepSeek 958× (~$1.92) — mostly genuine new postings, not re-scores.
The variant's remaining edge is *time-windowed* skip (skip jobs scored
in last N days regardless of rubric); marginal at 1 run/day.
**Still worth doing** for single-source-of-truth (job_scores DB vs
shortlist.json file) — code hygiene, not cost.
**Re-promote if:** `RUBRIC_VERSION` bumps invalidate the cache
wholesale (a single run would then hit DeepSeek on ~1,000 jobs ≈ $2),
at which point time-windowed skip becomes the cheap mitigation.

### 8. Fold URL enrichment into discover_phase
One-off enrichment already executed (`scripts/url_enrichment.py`,
`tools/enrich_urls_oneshot.py`, `tools/migration_add_enrichment_cache.sql`)
and the 200-400 endpoint yield is captured. **Decision 2026-05-06:**
integrate into `discover_phase()` so newly-added companies get URL
enrichment automatically before probing — single integration point,
no separate manual step. Deprioritized; do this when next touching
the discover/scout flow, not as standalone work.

### 9. JS-rendered careers page support — demoted from T2 on 2026-05-08
**Yield:** indeterminate, likely <15 endpoints (was assumed +190 before
the spike). **Effort:** High — Playwright infra, ~2-3 days.

The original Tier 2 framing assumed all 190 SPA-categorized companies would
yield a recoverable slug after JS rendering. Two scoping passes invalidated
this:
- **HTTP hostname-mention scan (n=190):** 2 / 190 (1%) mention any provider
  hostname in static HTML.
- **Playwright spike (n=20 random SPAs):** 0 / 20 slug hits, 1 / 20
  hostname-only hit (ThoughtSpot → Workday, unsupported).

The 190 SPA bucket is dominated by in-house ATS implementations or
third-party boards that require user interaction (button clicks) to reveal,
which passive rendering misses. **Demoted because:** real yield is too
small to justify the infrastructure cost. Note: at the time of the
spike the one provider observed behind SPAs (Workday) wasn't yet
supported; Workday shipped 2026-05-08, so a re-spike using the
production detector might find marginally more.
**Re-promote if:** a click-driven scraper, paid scraping API, or
LLM-assisted careers-page parsing surfaces as a viable alternative.
**Reference:** `docs/investigations/2026-05-07_phase2_unknown_audit.md`
(Addendum 2026-05-08).

## Tier 4 — Strategic (requires solid foundation first)

### 10. 5K company expansion — in progress
Original goal that started this whole effort. Premature until ATS
detection catches up. Reconsider once active endpoints ≥ 2,500.
Sources identified: 899 Getro VCs at community.getro.com, tier-2 VCs
(645 Ventures, 8VC, BCV, Battery, CRV, Emergence, Felicis, FirstMark,
Foundation, IVP, Lerer Hippeau, Lux, Mayfield, Menlo, Norwest, Redpoint,
Spark, Threshold, Union Square, Upfront), YC Work at a Startup
(~1,000 cos), Tiger/Insight/Founders Fund/Coatue/Thrive/Index (custom
scraping required).

**Update 2026-05-11:** non-VC sourcing path opened up. Ingestion architecture
landed (see CHANGELOG 2026-05-11) — Fortune 1000 (+972) and Built In BPTW
2025 (+1,797 unique) loaded in one pass. Companies table now at 5,939; ATS
discover phase running on the 2,804 newly-eligible companies.

**Update 2026-05-12:** discover phase finished — `tried=2804, hits=828`.
Active endpoints went 1,309 → 2,078 (+769). Audited the funnel: URL-capture
step holds back 39.2% of total cos (mostly Built In, which we deferred URL
fetching for). Detector-step holds back 36.3% (Fortune cos are 72% Workday +
17% Greenhouse + 5% Ashby + 5% Lever among the wins; failures are
Phenom/Oracle HCM/Eightfold/Avature-heavy among the largest cos).

**Recovery work started today** (still running at end of session):
- **Built In URL backfill via Tavily** — direct scrape IP-banned us, switched
  to Tavily search API; ~99% URL recovery rate on the first 150 of 1,746
  targets; full run ETA 30 min.
- **Phase A: header upgrade** to `_http_get_text` (CHANGELOG 2026-05-12)
  recovered ~6 large Workday cos in the first 150 of Fortune redetect →
  est. +50 active endpoints when redetect completes.

Reconsider VC-list expansion only after these two finish AND we've shipped
the Phenom + Oracle HCM detectors (~140 cos estimated yield, see CHANGELOG
2026-05-12 audit). Still gated on active endpoints ≥ 2,500 (currently 2,078).

### 11. SEC Form D scraper integration
`edgar_formd_scraper.py` exists as sibling experiment. Promote into
the run-time pipeline as "newly-funded" sourcing signal once #10 is active.

### 12. Browser agent for assisted form-filling
Largest item; separate workstream. Don't scope until everything above
is in flight.

## Cleanup (do during related work)

### 13. Remove legacy hardcoded COMPANIES fallback
SQLite-backed paths are now default. Remove the in-script `COMPANIES`
list and `PP_JOBAPP_COMPANY_SOURCE=legacy` escape hatch from
`ats_scout.py` during the next session that touches it.

---

## Removed

### 2026-05-08
- **Workday provider support (was T2 #2)** — shipped 2026-05-08. +27 active
  endpoints (84% of 32 audit-identified), ~5,200 jobs added to scan
  rotation. See CHANGELOG 2026-05-08. Follow-ups left open:
  - 4 companies (Criteo, Uniphore, Trifacta, Thrasio) returned 403 on
    every careers-page probe path — anti-bot blocking, candidates for
    a future UA-rotation effort.
  - 1 company (Accolade, tenant `osv-accolade`) hits a tenant-specific
    HTTP 422 on the cxs jobs API. The "OSV"-style Workday tenants may
    require a different request body shape; punted.
  - Workday's listing endpoint returns title-only. If match yield from
    Workday boards is low after the next scoring pass, add per-job
    detail fetching so JD-fallback can fire.
- **applied_history.json** — already implemented. The `job_interactions.applied`
  column exists and the dashboard has full filter + badge + stat-counter
  support (`scripts/dashboard_ui.html:300, 323-326, 615-619, 673`).

### 2026-05-06
- **Daily pipeline cron** — superseded by manual-trigger-only design decision.
