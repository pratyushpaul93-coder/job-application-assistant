"""Phase 2 research: probe a sample of 'unknown/not_found' companies and
categorize what's blocking ATS detection.

Pure HTTP + regex. No LLM calls, no web_search. Fully free to run.

Outputs (all under workspace/):
    phase2_probe_results_<DATE>.csv  - one row per company with category + evidence
    phase2_run_<DATE>.log            - info-level run log (progress, summary)
    phase2_errors_<DATE>.log         - errors only (DNS, HTTP, parse failures)
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import re
import socket
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(ROOT, "workspace")
DB_PATH = os.path.join(WORKSPACE, "jobapp.db")

CAREERS_PATHS = ["/careers", "/jobs", "/career", "/work-with-us", "/join", "/join-us", "/about/careers"]
UA = "Mozilla/5.0 (compatible; pp-jobapp-audit/1.0)"
HTTP_TIMEOUT = 8

# Provider patterns checked AGAINST raw HTML (homepage and careers pages).
# Order matters: more specific patterns first (e.g. greenhouse-embed-js before generic greenhouse).
PROVIDER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse_embed_js_bug", re.compile(r"boards\.greenhouse\.io/embed/job_board/js\?for=([a-zA-Z0-9_-]+)", re.I)),
    ("greenhouse",              re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-zA-Z0-9_-]+)", re.I)),
    ("ashby",                   re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_.%-]+)", re.I)),
    ("lever",                   re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)", re.I)),
    ("workable",                re.compile(r"apply\.workable\.com/([a-zA-Z0-9_-]+)", re.I)),
    ("smartrecruiters",         re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([a-zA-Z0-9_-]+)", re.I)),
    ("workday",                 re.compile(r"([a-zA-Z0-9_-]+)\.(?:wd[0-9]+|myworkday(?:jobs)?)\.com/([a-zA-Z0-9_/-]+)?", re.I)),
    ("icims",                   re.compile(r"([a-zA-Z0-9_-]+)\.icims\.com", re.I)),
    ("bullhorn",                re.compile(r"(?:bullhornreach|bullhorn)\.com/[a-zA-Z0-9_/?=&-]+", re.I)),
    ("taleo",                   re.compile(r"([a-zA-Z0-9_-]+)\.taleo\.net", re.I)),
    ("successfactors",          re.compile(r"successfactors\.com/[a-zA-Z0-9_/?=&-]+", re.I)),
    ("jobvite",                 re.compile(r"jobs\.jobvite\.com/([a-zA-Z0-9_-]+)", re.I)),
    ("breezy",                  re.compile(r"([a-zA-Z0-9_-]+)\.breezy\.hr", re.I)),
    ("phenom",                  re.compile(r"phenompeople\.com/[a-zA-Z0-9_/?=&-]+", re.I)),
    ("recruiterflow",           re.compile(r"recruiterflow\.com/([a-zA-Z0-9_-]+)", re.I)),
    ("eightfold",               re.compile(r"([a-zA-Z0-9_-]+)\.eightfold\.ai", re.I)),
    ("cornerstone",             re.compile(r"([a-zA-Z0-9_-]+)\.cornerstoneondemand\.com", re.I)),
    ("brassring",               re.compile(r"([a-zA-Z0-9_-]+)\.brassring\.com", re.I)),
    ("bamboohr",                re.compile(r"([a-zA-Z0-9_-]+)\.bamboohr\.com", re.I)),
    ("personio",                re.compile(r"([a-zA-Z0-9_-]+)\.jobs\.personio", re.I)),
    ("recruitee",               re.compile(r"([a-zA-Z0-9_-]+)\.recruitee\.com", re.I)),
    ("jazzhr",                  re.compile(r"([a-zA-Z0-9_-]+)\.applytojob\.com", re.I)),
    ("teamtailor",              re.compile(r"([a-zA-Z0-9_-]+)\.teamtailor\.com", re.I)),
    # comeet excluded: regex without a stable capture group produces false-positive
    # missed_by_discover hits on generic API URLs (e.g., comeet.co/careers-api/api).
    # Only 1 comeet endpoint exists in the DB; lost detection is negligible.
    ("jobscore",                re.compile(r"jobscore\.com/[a-zA-Z0-9_/?=&-]+", re.I)),
]

SPA_MARKERS = re.compile(
    r'__NEXT_DATA__|data-reactroot|ng-app=|<div id="root"[^>]*></div>|<div id="__nuxt">|window\.__NUXT__|webpackJsonp',
    re.I,
)
MAILTO_RE = re.compile(r'href="mailto:[^"]*(?:careers|jobs|hiring|hr|recruit)[^"]*"', re.I)

# Providers currently in scripts/storage.py:_ATS_SIGNATURES. Finding any of these
# on a company in the unknown/not_found bucket is a "missed by discover" hit:
# the existing detector should have caught it. Keep this in sync with storage.py.
SUPPORTED_PROVIDERS = {
    "greenhouse", "ashby", "lever", "workable", "smartrecruiters",
    "bamboohr", "personio", "recruitee", "jazzhr", "teamtailor", "comeet",
}


def bucket_error(err: str) -> str:
    """Classify a fetch() error string into one taxonomy bucket.

    Buckets are defined in docs/definitions.md. Format reference: see fetch()
    return values for the source error string formats.
    """
    if not err:
        return "other"
    m = re.match(r"HTTPError (\d{3})", err)
    if m:
        code = int(m.group(1))
        if code == 403: return "http_403"
        if code == 404: return "http_404"
        if 400 <= code < 500: return "http_4xx"
        if 500 <= code < 600: return "http_5xx"
    e = err.lower()
    if ("name or service not known" in e or "no address associated" in e
            or "nodename nor servname" in e or "name resolution" in e):
        return "dns_nxdomain"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if "decodeerror" in e:
        return "decode_error"
    return "other"


def is_missed_by_discover(category: str) -> bool:
    """True if the category indicates a detector failure (see docs/definitions.md)."""
    if category == "greenhouse_embed_js_bug":
        return True
    if category.startswith("has_provider:"):
        return category.split(":", 1)[1] in SUPPORTED_PROVIDERS
    return False


def fetch(url: str) -> tuple[int | None, str, str | None]:
    """Returns (status_code, body, error). status_code is None if no HTTP response."""
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read(2_000_000).decode("utf-8", errors="replace"), None
    except HTTPError as e:
        return e.code, "", f"HTTPError {e.code} {e.reason}"
    except URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        return None, "", f"URLError {reason}"
    except (socket.timeout, TimeoutError):
        return None, "", "Timeout"
    except UnicodeDecodeError as e:
        return None, "", f"DecodeError {e}"
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"


def absolute(base: str, path: str) -> str:
    p = urlparse(base)
    return urlunparse((p.scheme or "https", p.netloc, path, "", "", ""))


def categorize(html: str) -> dict:
    """Pure-function classifier; no network. Returns dict with keys:
        category, evidence, provider (str|None), slug (str|None).

    Categories:
      - greenhouse_embed_js_bug : matches the buggy-regex variant
      - has_provider:<name>     : found a known provider pattern in static HTML
      - js_rendered_spa         : SPA markers present, content likely loaded by JS
      - mailto_only             : only a careers email link
      - static_in_house         : has 'careers'/'job' word but no detectable pattern
      - empty_or_tiny           : page body too short to assess
    """
    if not html or len(html) < 500:
        return {"category": "empty_or_tiny", "evidence": f"body_len={len(html or '')}",
                "provider": None, "slug": None}

    for name, pat in PROVIDER_PATTERNS:
        m = pat.search(html)
        if m:
            snippet = m.group(0)[:120]
            slug = m.group(1) if m.lastindex else None
            if name == "greenhouse_embed_js_bug":
                return {"category": "greenhouse_embed_js_bug", "evidence": snippet,
                        "provider": "greenhouse", "slug": slug}
            return {"category": f"has_provider:{name}", "evidence": snippet,
                    "provider": name, "slug": slug}

    if SPA_MARKERS.search(html):
        m = SPA_MARKERS.search(html)
        return {"category": "js_rendered_spa", "evidence": (m.group(0) if m else "")[:120],
                "provider": None, "slug": None}

    if MAILTO_RE.search(html):
        m = MAILTO_RE.search(html)
        return {"category": "mailto_only", "evidence": (m.group(0) if m else "")[:120],
                "provider": None, "slug": None}

    has_career_word = bool(re.search(r"\b(careers?|jobs|hiring|join us)\b", html, re.I))
    if has_career_word:
        return {"category": "static_in_house", "evidence": f"len={len(html)} no_provider_match",
                "provider": None, "slug": None}

    return {"category": "empty_or_tiny", "evidence": f"len={len(html)} no_career_keyword",
            "provider": None, "slug": None}


# Live-check URLs per provider. A 200 response means the slug is a real, hittable
# board; non-200 (and especially 404) means the careers page is referencing a
# dead/private/removed board (a stale link, not a detector miss).
SLUG_VERIFY_URLS = {
    "greenhouse":      "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
    "ashby":           "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "lever":           "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "workable":        "https://apply.workable.com/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
    "bamboohr":        "https://{slug}.bamboohr.com/jobs/",
    "personio":        "https://{slug}.jobs.personio.com",
    "recruitee":       "https://{slug}.recruitee.com/api/offers/",
    "jazzhr":          "https://{slug}.applytojob.com",
    "teamtailor":      "https://{slug}.teamtailor.com",
    "comeet":          "https://www.comeet.co/jobs-api/2.2/company/{slug}",
}


def verify_slug_live(provider: str, slug: str) -> bool | None:
    """One HTTP HEAD/GET to the provider's API. Returns True if the slug is
    served as a real board, False if confirmed dead (e.g., 404), None if the
    check itself errored (treat as inconclusive — keep original category).
    """
    tmpl = SLUG_VERIFY_URLS.get(provider)
    if not tmpl or not slug:
        return None
    url = tmpl.format(slug=slug)
    status, _, _ = fetch(url)
    # status is None only when there was no HTTP response at all (DNS / timeout /
    # connection error). HTTP error codes (e.g., 404) come back as status=code.
    if status is None:
        return None
    return 200 <= status < 300


def _make_result(cid, name, url, tried, status, category, evidence) -> dict:
    return {"id": cid, "name": name, "url": url, "tried": tried,
            "status": str(status or ""), "category": category, "evidence": evidence,
            "missed_by_discover": is_missed_by_discover(category)}


def probe_company(row: dict, log_err) -> tuple[dict, list[str]]:
    """Probe homepage + careers paths.

    Returns (result_dict, error_buckets) where error_buckets contains one
    bucket name per failed fetch attempt (so a company that fails 3 paths
    contributes 3 entries to the run-wide error taxonomy).

    Provider hits get one extra HTTP call to verify the slug is live in the
    provider's API. Dead slugs are downgraded to `stale_provider_link:<provider>`
    so they don't pollute the missed-by-discover count.
    """
    cid = row["id"]
    name = row["canonical_name"]
    url = (row["website_url"] or "").rstrip("/")
    error_buckets: list[str] = []
    if not url:
        return _make_result(cid, name, "", "", "", "no_url", ""), error_buckets

    candidates = [url] + [absolute(url, p) for p in CAREERS_PATHS]
    best: dict | None = None
    last_err = None
    for cand in candidates:
        status, body, err = fetch(cand)
        if err is not None:
            error_buckets.append(bucket_error(err))
            last_err = err
            log_err(f"[{cid} {name!r}] {cand} -> {err}")
            continue
        info = categorize(body)
        category = info["category"]
        evidence = info["evidence"]

        # Verify supported-provider hits; downgrade stale ones.
        if info["provider"] in SUPPORTED_PROVIDERS and info["slug"]:
            live = verify_slug_live(info["provider"], info["slug"])
            if live is False:
                category = f"stale_provider_link:{info['provider']}"
                evidence = f"{evidence} [SLUG_DEAD]"
            elif live is None:
                # Inconclusive — log but keep original category. May slightly
                # over-count missed_by_discover; preferable to silently dropping.
                log_err(f"[{cid} {name!r}] verify_slug_live({info['provider']!r}, {info['slug']!r}) inconclusive")

        result = _make_result(cid, name, url, cand, status, category, evidence)

        # Early-return only on confirmed-live (or unverifiable) provider hits,
        # not on stale ones — keep iterating in case a later path has a live hit.
        is_live_provider_hit = (
            info["provider"] is not None
            and not category.startswith("stale_provider_link")
        )
        if is_live_provider_hit:
            return result, error_buckets

        if best is None or (best["category"] in ("empty_or_tiny", "no_url") and category != "empty_or_tiny"):
            best = result

    if best is not None:
        return best, error_buckets
    return (_make_result(cid, name, url, ",".join(candidates[:2]), "", "unreachable", last_err or ""),
            error_buckets)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=100, help="Sample size (default 100)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()

    today = datetime.date.today().isoformat().replace("-", "")
    csv_path = os.path.join(WORKSPACE, f"phase2_probe_results_{today}.csv")
    log_path = os.path.join(WORKSPACE, f"phase2_run_{today}.log")
    err_path = os.path.join(WORKSPACE, f"phase2_errors_{today}.log")

    log_fh = open(log_path, "a")
    err_fh = open(err_path, "a")

    def log(msg):
        line = f"{datetime.datetime.now().isoformat()} {msg}\n"
        log_fh.write(line); log_fh.flush()
        print(msg, flush=True)

    def log_err(msg):
        err_fh.write(f"{datetime.datetime.now().isoformat()} {msg}\n"); err_fh.flush()

    log(f"=== Phase 2 unknown audit start (n={args.n}, workers={args.workers}) ===")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    seed_clause = f", {args.seed}" if args.seed is not None else ""
    rows = conn.execute(
        f"""
        SELECT c.id, c.canonical_name, c.website_url
        FROM companies c
        WHERE c.active=1
          AND c.website_url IS NOT NULL AND c.website_url != ''
          AND EXISTS (SELECT 1 FROM ats_endpoints e
                      WHERE e.company_id=c.id AND e.provider='unknown' AND e.status='not_found')
          AND NOT EXISTS (SELECT 1 FROM ats_endpoints e
                          WHERE e.company_id=c.id AND e.status='active')
        ORDER BY RANDOM({args.seed if args.seed is not None else ''})
        LIMIT ?
        """,
        (args.n,),
    ).fetchall()
    conn.close()
    log(f"Sampled {len(rows)} companies")

    results: list[dict] = []
    all_err_buckets: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(probe_company, dict(r), log_err): dict(r) for r in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                res, errs = fut.result()
                results.append(res)
                all_err_buckets.extend(errs)
            except Exception as e:
                row = futures[fut]
                log_err(f"[{row['id']} {row['canonical_name']!r}] FATAL: {type(e).__name__}: {e}")
                results.append(_make_result(row["id"], row["canonical_name"],
                                            row.get("website_url", ""), "", "",
                                            "fatal_error", str(e)[:200]))
            if i % 20 == 0:
                log(f"  progress {i}/{len(rows)}")

    # Write CSV
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "url", "tried", "status",
                                          "category", "evidence", "missed_by_discover"])
        w.writeheader()
        for r in results:
            w.writerow(r)
    log(f"Wrote {csv_path}")

    # Category distribution
    counts: dict[str, int] = {}
    for r in results:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    log("=== Category distribution ===")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        log(f"  {n:4d}  {cat}")

    # Missed by discover (detector-failure signal — see docs/definitions.md)
    missed_rows = [r for r in results if r.get("missed_by_discover")]
    log(f"=== Missed by discover: {len(missed_rows)} of {len(results)} ===")
    for r in missed_rows:
        log(f"  [{r['id']:5d}] {r['name']:<28.28} {r['category']:<32.32} {r['evidence'][:60]}")

    # Error taxonomy aggregation (see docs/definitions.md)
    err_counts = Counter(all_err_buckets)
    log(f"=== Error taxonomy ({sum(err_counts.values())} total fetch errors) ===")
    if err_counts:
        for bucket, n in sorted(err_counts.items(), key=lambda kv: -kv[1]):
            log(f"  {n:4d}  {bucket}")
    else:
        log("  (none)")

    log("=== Phase 2 done ===")

    log_fh.close()
    err_fh.close()


if __name__ == "__main__":
    main()
