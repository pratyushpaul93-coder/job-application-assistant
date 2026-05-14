"""
url_enrichment.py
=================
Pure functions for LLM-based company URL enrichment.

Designed to be called from:
  - tools/enrich_urls_oneshot.py (batch backfill)
  - scripts/bulk_add_companies.py (onboarding hot path, future)
  - dashboard manual-add flow (future)

Tier 1: DeepSeek without web search (~$0.05 for 1,022 companies)
Tier 2: Claude Haiku 4.5 with web_search tool (~$0.50-1 for tier-1 failures)
Verify: HEAD request with HEAD->GET fallback for sites that block HEAD.

Returns from enrich_url():
    EnrichmentResult dataclass with:
      url            : str | None        -- normalized URL (https://example.com), None if unknown
      source         : str               -- 'cache' | 'deepseek' | 'claude_websearch' | 'unknown'
      confidence     : str               -- 'high' | 'medium' | 'low' | 'none'
      head_status    : int | None        -- HTTP status from verify; None if not run
      reasoning      : str               -- model rationale
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import requests

from keys import get_anthropic_key, get_deepseek_key


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEEPSEEK_API_URL  = "https://api.deepseek.com/v1/chat/completions"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

DEEPSEEK_MODEL = "deepseek-chat"
CLAUDE_MODEL   = "claude-haiku-4-5-20251001"

DEEPSEEK_BATCH_SIZE = 20      # companies per DeepSeek call
DEEPSEEK_WORKERS    = 4       # concurrent batches
CLAUDE_WORKERS      = 1       # tier-2 sequential (web search adds latency, rate limits are tight)
CLAUDE_PACING_SEC   = 1.2     # sleep between tier-2 calls to stay under rate limits

HEAD_TIMEOUT     = 5.0
LLM_TIMEOUT      = 60.0

# Retry config for 429s
RATE_LIMIT_MAX_RETRIES = 6           # was 4
RATE_LIMIT_BASE_BACKOFF_SEC = 2.0    # exponential: 2, 4, 8, 16, 32, 60(cap)
RATE_LIMIT_MAX_BACKOFF_SEC = 60.0    # per-attempt cap


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EnrichmentResult:
    name_original: str
    url: Optional[str]
    source: str            # 'cache' | 'deepseek' | 'claude_websearch' | 'unknown'
    confidence: str        # 'high' | 'medium' | 'low' | 'none'
    head_status: Optional[int]
    reasoning: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize for cache key. Strips suffixes, punctuation, case, whitespace."""
    s = name.lower().strip()
    # Strip common suffixes
    for suffix in [", inc.", ", inc", " inc.", " inc", ", llc", " llc",
                   ", ltd.", " ltd.", " ltd", ", pbc", " pbc", " corp",
                   " corp.", " corporation", " co.", " company"]:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    # Collapse whitespace, strip non-alphanumeric except spaces
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_url(url: str) -> Optional[str]:
    """Coerce to https://apex-or-www-domain. Returns None if invalid."""
    if not url:
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        if not parsed.netloc or "." not in parsed.netloc:
            return None
        # Force https
        return f"https://{parsed.netloc}{parsed.path or ''}".rstrip("/")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HEAD verify
# ---------------------------------------------------------------------------

def head_verify(url: str) -> Optional[int]:
    """
    Returns HTTP status code if reachable, None if DNS/timeout/connection failure.
    Falls back from HEAD to GET(stream=True) for 405-blocked sites.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; pp-jobapp-enricher/1.0)"}
    try:
        r = requests.head(url, timeout=HEAD_TIMEOUT, allow_redirects=True, headers=headers)
        if r.status_code == 405:
            # HEAD blocked; try GET with stream
            r = requests.get(url, timeout=HEAD_TIMEOUT, allow_redirects=True,
                             headers=headers, stream=True)
            r.close()
        return r.status_code
    except requests.exceptions.RequestException:
        return None


def head_status_ok(status: Optional[int]) -> bool:
    """
    Returns True if the HEAD response indicates a live site.
    Accepts:
      - 200-399 (success + redirects)
      - 401, 403 (auth required / bot-detection blocking — site is alive,
                  it's just refusing this specific request)
    Rejects:
      - None (DNS fail / timeout / connection error)
      - 404, 410 (not found / gone)
      - 4xx other than 401/403
      - 5xx (server error)
    """
    if status is None:
        return False
    if 200 <= status < 400:
        return True
    if status in (401, 403):
        return True
    return False


# ---------------------------------------------------------------------------
# Prose URL extraction (fallback for when LLM returns natural language)
# ---------------------------------------------------------------------------

# Domains we never want to extract — these are search engines, social, refs, etc.
_BLOCKLIST_DOMAINS = {
    "linkedin.com", "crunchbase.com", "wikipedia.org", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "github.com", "google.com",
    "anthropic.com", "openai.com",  # avoid the model citing itself
    "pitchbook.com", "owler.com", "tracxn.com",
}


def _extract_url_from_prose(text: str) -> Optional[str]:
    """
    When LLM returns prose instead of JSON, try to find a plausible primary URL.
    Returns first non-blocklisted URL found, or None.

    Strategy:
      1. Find all URL-shaped strings
      2. Filter out blocklisted domains (LinkedIn, Crunchbase, etc.)
      3. Prefer ones that appear after positive markers ("official site", "homepage")
      4. Fall back to the first one that survives filtering
    """
    if not text:
        return None

    # Find all URL-like strings
    url_pattern = re.compile(
        r"https?://(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s\"'<>)\]]*)?"
    )
    candidates = url_pattern.findall(text)
    if not candidates:
        # Try bare-domain pattern as last resort (e.g., "tackle.io")
        domain_pattern = re.compile(
            r"\b([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.[a-zA-Z]{2,})\b"
        )
        bare = domain_pattern.findall(text)
        candidates = [f"https://{d}" for d in bare]

    # Filter blocklist
    def is_blocklisted(url: str) -> bool:
        try:
            netloc = urlparse(url).netloc.lower()
            # Strip leading www.
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return any(netloc == bad or netloc.endswith("." + bad)
                       for bad in _BLOCKLIST_DOMAINS)
        except Exception:
            return True

    # Strip trailing punctuation that the regex may have grabbed
    def clean(url: str) -> str:
        return url.rstrip(".,;:)!?\"'>]")

    candidates = [clean(c) for c in candidates]
    filtered = [u for u in candidates if not is_blocklisted(u)]
    if not filtered:
        return None

    # Prefer URLs near positive markers
    positive_markers = [
        "official site", "official website", "homepage", "company website",
        "is the official", "their site", "their website",
    ]
    text_lower = text.lower()
    for url in filtered:
        # Find the URL position; check if any positive marker appears within ~80 chars before it
        pos = text.find(url)
        if pos > 0:
            prefix = text_lower[max(0, pos - 80):pos]
            if any(marker in prefix for marker in positive_markers):
                return url

    # Fall back to first non-blocklisted URL
    return filtered[0]


# ---------------------------------------------------------------------------
# Tier 1: DeepSeek (batched, no web search)
# ---------------------------------------------------------------------------

DEEPSEEK_SYSTEM_PROMPT = """You are a company-URL lookup assistant. For each company name provided, return the official primary website URL.

Rules:
- Return ONLY companies you are confident exist. Do NOT invent URLs.
- Prefer the corporate/marketing site (e.g., anthropic.com), not subdomains, not LinkedIn, not Crunchbase.
- If multiple companies share a name, pick the most prominent tech company. If unsure, mark confidence 'low' or 'unknown'.
- confidence='high' means you are certain the URL is correct.
- confidence='medium' means you believe the URL is correct but there is some ambiguity (similar names, recent rebrand, etc.).
- confidence='low' means you are guessing based on naming conventions.
- confidence='unknown' means you do not know this company - return url=null.

Output format: a JSON array of objects, in the same order as input, each with fields {name, url, confidence, reasoning}. reasoning is a short (max 15 words) explanation. Output ONLY the JSON array, no markdown fences, no preamble."""


def _deepseek_batch(names: List[str], api_key: str) -> List[Dict[str, Any]]:
    """Single DeepSeek call for a batch of names. Returns list of dicts."""
    user_msg = "Companies:\n" + "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 2000,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }

    # DeepSeek's json_object mode wants the prompt to mention JSON; system prompt does.
    # But it returns a JSON object, not array - so wrap our request.
    payload["messages"][1]["content"] += "\n\nReturn JSON in shape: {\"results\": [...]}"

    resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    try:
        parsed = json.loads(content)
        results = parsed.get("results", [])
        if not isinstance(results, list):
            raise ValueError("results not a list")
        return results
    except (json.JSONDecodeError, ValueError) as e:
        # On parse failure, return 'unknown' for all in batch
        return [{"name": n, "url": None, "confidence": "unknown",
                 "reasoning": f"parse_error: {e}"} for n in names]


def deepseek_enrich_many(names: List[str], api_key: str,
                         progress_callback=None) -> List[Dict[str, Any]]:
    """
    Enrich many names via DeepSeek with batching and concurrency.
    Returns list of dicts in same order as input.
    """
    # Split into batches
    batches: List[List[str]] = [
        names[i:i + DEEPSEEK_BATCH_SIZE]
        for i in range(0, len(names), DEEPSEEK_BATCH_SIZE)
    ]

    # Index batches so we can reassemble in order
    indexed_batches = list(enumerate(batches))
    batch_results: Dict[int, List[Dict[str, Any]]] = {}

    completed = 0
    with ThreadPoolExecutor(max_workers=DEEPSEEK_WORKERS) as ex:
        future_to_idx = {
            ex.submit(_deepseek_batch, batch, api_key): idx
            for idx, batch in indexed_batches
        }
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                batch_results[idx] = fut.result()
            except Exception as e:
                # Whole batch failed - mark all unknown
                batch_results[idx] = [
                    {"name": n, "url": None, "confidence": "unknown",
                     "reasoning": f"api_error: {e}"}
                    for n in batches[idx]
                ]
            completed += 1
            if progress_callback:
                progress_callback(completed, len(batches))

    # Reassemble in order; align with original names by position within batch
    out: List[Dict[str, Any]] = []
    for idx, batch in indexed_batches:
        results = batch_results.get(idx, [])
        # Pad/truncate if model returned wrong count
        for i, name in enumerate(batch):
            if i < len(results):
                r = results[i]
                # Trust positional alignment over the model's echoed name
                r["name"] = name
                out.append(r)
            else:
                out.append({"name": name, "url": None, "confidence": "unknown",
                            "reasoning": "missing_from_batch_response"})
    return out


# ---------------------------------------------------------------------------
# Tier 2: Claude Haiku with web_search
# ---------------------------------------------------------------------------

CLAUDE_SYSTEM_PROMPT = """You look up the official website URL for a company. Use web search to verify.

CRITICAL OUTPUT RULES:
- Your final response MUST be a single valid JSON object and nothing else.
- Do NOT preface with explanation, narration, or "I'll search for..." style text.
- Do NOT wrap in markdown code fences.
- Do NOT add any text after the JSON.

JSON shape:
{"url": "https://...", "confidence": "high|medium|low|unknown", "reasoning": "short explanation, max 15 words"}

Set url=null and confidence=unknown if the company does not exist or you cannot find it.
Prefer the corporate/marketing site (e.g., anthropic.com), not LinkedIn, not Crunchbase, not Wikipedia.
If the company is defunct or acquired, still return the historical URL if known and add a note in reasoning."""


def _claude_websearch_one(name: str, api_key: str) -> Dict[str, Any]:
    """
    Single Claude Haiku + web_search call for one company.
    Retries on 429 with exponential backoff, respecting retry-after headers.
    """
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 500,
        "system": CLAUDE_SYSTEM_PROMPT,
        "messages": [{"role": "user",
                      "content": f"What is the official website URL for the company '{name}'?"}],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
    }
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }

    last_error: str = ""
    for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
        try:
            resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload,
                                 timeout=LLM_TIMEOUT)

            if resp.status_code == 429:
                # Honor retry-after header if present, else exponential backoff
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        sleep_sec = float(retry_after)
                    except ValueError:
                        sleep_sec = RATE_LIMIT_BASE_BACKOFF_SEC * (2 ** attempt)
                else:
                    sleep_sec = RATE_LIMIT_BASE_BACKOFF_SEC * (2 ** attempt)
                # Cap sleep to MAX_BACKOFF to avoid hangs
                sleep_sec = min(sleep_sec, RATE_LIMIT_MAX_BACKOFF_SEC)
                last_error = f"429 rate_limited (attempt {attempt+1}, slept {sleep_sec:.1f}s)"
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    time.sleep(sleep_sec)
                    continue
                # Final attempt failed; fall through to error return
                return {"name": name, "url": None, "confidence": "rate_limited",
                        "reasoning": f"rate_limited_after_{RATE_LIMIT_MAX_RETRIES}_retries"}

            resp.raise_for_status()
            data = resp.json()

            # Extract final text block (after any tool_use rounds)
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")

            text = text.strip()
            # Strip code fences if present
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

            try:
                parsed = json.loads(text)
                return {
                    "name":       name,
                    "url":        parsed.get("url"),
                    "confidence": parsed.get("confidence", "unknown"),
                    "reasoning":  parsed.get("reasoning", ""),
                }
            except json.JSONDecodeError:
                # JSON parse failed - Claude likely returned prose instead of JSON.
                # Try to recover by extracting a URL from the prose.
                extracted = _extract_url_from_prose(text)
                if extracted:
                    return {
                        "name":       name,
                        "url":        extracted,
                        "confidence": "medium",  # downgraded - prose extraction is less reliable
                        "reasoning":  f"prose_extract: {text[:80]}",
                    }
                return {"name": name, "url": None, "confidence": "unknown",
                        "reasoning": f"parse_error_no_url: {text[:100]}"}

        except requests.exceptions.RequestException as e:
            last_error = f"request_error: {e}"
            if attempt < RATE_LIMIT_MAX_RETRIES:
                time.sleep(RATE_LIMIT_BASE_BACKOFF_SEC * (2 ** attempt))
                continue
            return {"name": name, "url": None, "confidence": "unknown",
                    "reasoning": f"api_error_after_retries: {last_error}"}

    # Shouldn't reach here, but defensive
    return {"name": name, "url": None, "confidence": "unknown",
            "reasoning": f"unexpected_loop_exit: {last_error}"}


def claude_websearch_many(names: List[str], api_key: str,
                          progress_callback=None) -> List[Dict[str, Any]]:
    """
    Tier-2 enrich many names. Sequential (CLAUDE_WORKERS=1) with pacing
    between requests to stay under rate limits. Each call has internal 429
    retry-with-backoff via _claude_websearch_one.
    """
    results: Dict[str, Dict[str, Any]] = {}
    completed = 0

    # When CLAUDE_WORKERS=1, just iterate sequentially with pacing.
    # Avoids ThreadPoolExecutor overhead and keeps deterministic ordering.
    if CLAUDE_WORKERS <= 1:
        for i, name in enumerate(names):
            try:
                results[name] = _claude_websearch_one(name, api_key)
            except Exception as e:
                results[name] = {"name": name, "url": None, "confidence": "unknown",
                                 "reasoning": f"unexpected_error: {e}"}
            completed += 1
            if progress_callback:
                progress_callback(completed, len(names))
            # Pace between requests; don't sleep after the last one
            if i < len(names) - 1:
                time.sleep(CLAUDE_PACING_SEC)
        return [results[n] for n in names]

    # Concurrent path (kept for future tuning if rate limits ever loosen)
    with ThreadPoolExecutor(max_workers=CLAUDE_WORKERS) as ex:
        future_to_name = {ex.submit(_claude_websearch_one, n, api_key): n for n in names}
        for fut in as_completed(future_to_name):
            name = future_to_name[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                results[name] = {"name": name, "url": None, "confidence": "unknown",
                                 "reasoning": f"api_error: {e}"}
            completed += 1
            if progress_callback:
                progress_callback(completed, len(names))

    return [results[n] for n in names]


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def cache_get(db_path: str, name: str) -> Optional[EnrichmentResult]:
    """Look up a name in the enrichment_cache table."""
    norm = normalize_name(name)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name_original, url, source, confidence, head_status, reasoning "
            "FROM enrichment_cache WHERE name_normalized = ?",
            (norm,)
        ).fetchone()
        if not row:
            return None
        return EnrichmentResult(
            name_original=row[0], url=row[1], source="cache",
            confidence=row[3], head_status=row[4], reasoning=row[5] or "",
        )
    finally:
        conn.close()


def cache_put(db_path: str, result: EnrichmentResult) -> None:
    """Upsert an enrichment result into the cache."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO enrichment_cache
                (name_normalized, name_original, url, source, confidence,
                 head_status, reasoning, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name_normalized) DO UPDATE SET
                url         = excluded.url,
                source      = excluded.source,
                confidence  = excluded.confidence,
                head_status = excluded.head_status,
                reasoning   = excluded.reasoning,
                checked_at  = CURRENT_TIMESTAMP
            """,
            (normalize_name(result.name_original), result.name_original,
             result.url, result.source, result.confidence,
             result.head_status, result.reasoning),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API: enrich_url (single)
# ---------------------------------------------------------------------------

def enrich_url(name: str, db_path: str,
               deepseek_key: Optional[str] = None,
               anthropic_key: Optional[str] = None,
               use_cache: bool = True) -> EnrichmentResult:
    """
    Single-company enrichment, used by the onboarding hot path.

    Tier sequence: cache -> deepseek -> head_verify -> claude_websearch -> head_verify

    For batch backfill, use the run_pipeline() function below instead.
    """
    deepseek_key  = deepseek_key  or get_deepseek_key()
    anthropic_key = anthropic_key or get_anthropic_key()

    if use_cache:
        cached = cache_get(db_path, name)
        if cached is not None:
            return cached

    # Tier 1
    if deepseek_key:
        ds_results = deepseek_enrich_many([name], deepseek_key)
        ds = ds_results[0]
        candidate_url = normalize_url(ds.get("url") or "")
        confidence    = ds.get("confidence", "unknown")
        reasoning     = ds.get("reasoning", "")

        if candidate_url and confidence in ("high", "medium"):
            status = head_verify(candidate_url)
            if head_status_ok(status):
                result = EnrichmentResult(
                    name_original=name, url=candidate_url, source="deepseek",
                    confidence=confidence, head_status=status, reasoning=reasoning,
                )
                if use_cache:
                    cache_put(db_path, result)
                return result
            # else: fall through to tier 2

    # Tier 2
    if anthropic_key:
        cl_results = claude_websearch_many([name], anthropic_key)
        cl = cl_results[0]
        candidate_url = normalize_url(cl.get("url") or "")
        confidence    = cl.get("confidence", "unknown")
        reasoning     = cl.get("reasoning", "")

        if candidate_url:
            status = head_verify(candidate_url)
            if head_status_ok(status):
                result = EnrichmentResult(
                    name_original=name, url=candidate_url, source="claude_websearch",
                    confidence=confidence, head_status=status, reasoning=reasoning,
                )
                if use_cache:
                    cache_put(db_path, result)
                return result

    # Both tiers failed
    result = EnrichmentResult(
        name_original=name, url=None, source="unknown",
        confidence="none", head_status=None,
        reasoning="tier1+tier2 both failed or unavailable",
    )
    if use_cache:
        cache_put(db_path, result)
    return result
