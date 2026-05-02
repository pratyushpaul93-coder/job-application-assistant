"""
edgar_formd_scraper.py
----------------------
Scrapes SEC EDGAR for Form D filings (private fundraising rounds).

Two-stage pipeline:
  Stage 1 — Pull EDGAR's quarterly bulk index (form.idx), keep Form Type "D"
            rows (no D/A amendments), pre-filter on company name to drop
            obvious non-startups (funds, real estate, trusts, address-named
            entities) and tag the survivors as "clear_startup" or "ambiguous".
  Stage 2 — Fetch each survivor's primary_doc.xml, parse, run passes_filters,
            and save progressively so a crash mid-run doesn't lose progress.
            "clear_startup" candidates are processed before "ambiguous" ones.

EDGAR endpoints used:
  - Quarterly bulk index: https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx
  - Filing documents:     https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/primary_doc.xml
  - Submission data:      https://data.sec.gov/submissions/CIK{cik}.json (utility, unused in main pipeline)

SEC fair use: max 10 requests/sec, include User-Agent with name + email.
"""

import time
import json
import re
import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from lxml import etree

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
USER_AGENT = "PP-OpenClaw-Scraper pratyush@example.com"

EDGAR_BASE_URL   = "https://www.sec.gov"
EDGAR_FULL_INDEX = "https://www.sec.gov/Archives/edgar/full-index"
EDGAR_DATA_URL   = "https://data.sec.gov"

REQUEST_DELAY    = 0.12   # ~8 req/sec, safely under 10/sec limit
MAX_RETRIES      = 3
RETRY_BACKOFF    = 2.0    # seconds, doubles each retry


# ── HTTP client ───────────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/html, application/xml, text/plain",
})

def _get(url: str, params: dict = None, as_json: bool = True, retries: int = MAX_RETRIES):
    """Rate-limited GET with retry logic."""
    for attempt in range(retries):
        resp = None
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json() if as_json else resp.text
        except requests.HTTPError as e:
            status = resp.status_code if resp is not None else "?"
            if resp is not None and resp.status_code == 429:
                wait = RETRY_BACKOFF ** (attempt + 2)
                log.warning(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"HTTP {status} on {url}: {e}")
                return None
        except Exception as e:
            log.error(f"Request error (attempt {attempt+1}): {e}")
            if attempt == retries - 1:
                return None
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


# ── Stage 1: bulk index fetch + name pre-filter ──────────────────────────────

# Substrings that almost always indicate non-startup entities.
# Matched as whole words, case-insensitive.
NOISE_PATTERNS = [
    "fund", "partners", "capital partners", "investment fund",
    "equity fund", "credit fund", "venture fund", "hedge fund",
    "realty", "real estate", "property", "reit", "dst", "housing",
    "apartment", "residential", "commercial", "series of", "spv",
    "feeder", "co-invest", "trust", "estate",
]

# Whole-word keywords that indicate a likely startup.
STARTUP_SIGNALS = [
    "inc", "corp", "technologies", "tech", "software", "ai", "bio",
    "health", "labs", "therapeutics", "systems", "digital", "data",
    "cloud", "medical", "pharma", "devices", "saas",
]

# Suffix words that signal a street-address-style name like "123 Main Street LLC".
STREET_SUFFIXES = [
    "street", "st", "ave", "avenue", "road", "rd", "blvd",
    "boulevard", "dr", "drive", "lane", "ln", "way", "hwy",
    "highway", "place", "pl", "court", "ct", "parkway", "pkwy",
    "trail",
]

_STREET_RE = re.compile(
    r'^\s*\d+\s+\S+.*\b(?:' + '|'.join(STREET_SUFFIXES) + r')\b',
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(p) for p in NOISE_PATTERNS) + r')\b',
    re.IGNORECASE,
)
_STARTUP_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(p) for p in STARTUP_SIGNALS) + r')\b',
    re.IGNORECASE,
)


def classify_company_name(name: str) -> Optional[str]:
    """
    Apply name-based pre-filter.
    Returns "clear_startup", "ambiguous", or None (skip as noise).
    """
    if not name or not name.strip():
        return None
    n = name.strip()
    if _STREET_RE.match(n):
        return None
    if _NOISE_RE.search(n):
        return None
    if _STARTUP_RE.search(n):
        return "clear_startup"
    return "ambiguous"


def quarters_for_range(start_date: str, end_date: str) -> list[tuple[int, int]]:
    """List (year, quarter) pairs that cover the inclusive date range."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end   = datetime.strptime(end_date, "%Y-%m-%d")
    if start > end:
        raise ValueError(f"start_date {start_date} after end_date {end_date}")

    quarters: list[tuple[int, int]] = []
    cur = start.replace(day=1)
    while cur <= end:
        q = (cur.month - 1) // 3 + 1
        if (cur.year, q) not in quarters:
            quarters.append((cur.year, q))
        cur = (cur.replace(year=cur.year + 1, month=1)
               if cur.month == 12
               else cur.replace(month=cur.month + 1))
    return quarters


def fetch_form_idx(year: int, quarter: int) -> Optional[str]:
    """Download the EDGAR quarterly form.idx text file."""
    url = f"{EDGAR_FULL_INDEX}/{year}/QTR{quarter}/form.idx"
    log.info(f"Fetching bulk index: {url}")
    return _get(url, as_json=False)


# form.idx is fixed-width but header column widths don't match data column
# widths (data fields are padded wider). The date column has a strict
# YYYY-MM-DD shape we can anchor on, so a regex per row is cleaner than slicing.
_FORMIDX_ROW_RE = re.compile(
    r'^(?P<form>\S+)\s{2,}'
    r'(?P<name>.+?)\s{2,}'
    r'(?P<cik>\d+)\s+'
    r'(?P<date>\d{4}-\d{2}-\d{2})\s+'
    r'(?P<file>\S+)'
)


def parse_form_idx(text: str) -> list[dict]:
    """
    Parse form.idx into a list of dicts. Returns only Form Type == "D" rows
    (excluding D/A amendments).
    """
    if not text:
        return []

    rows: list[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("-") or line.startswith(" "):
            # Skip dashes, blank, and any indented preamble lines.
            # (Real Form D data rows always start with the form-type token.)
            continue
        m = _FORMIDX_ROW_RE.match(line)
        if not m:
            continue
        if m.group("form") != "D":
            continue

        filename  = m.group("file")
        acc_match = re.search(r'(\d{10}-\d{2}-\d{6})', filename)
        accession = acc_match.group(1) if acc_match else ""
        if not accession:
            continue

        rows.append({
            "company_name": m.group("name").strip(),
            "cik":          m.group("cik").lstrip("0"),
            "filed_at":     m.group("date"),
            "accession_no": accession,
        })
    return rows


def stage1_bulk_filter(start_date: str, end_date: str) -> list[dict]:
    """
    Stage 1: fetch quarterly bulk indexes covering the date range, parse out
    Form D rows, restrict to the inclusive date window, and apply the
    name-based pre-filter.

    Returns a list of dicts with keys: company_name, cik, filed_at,
    accession_no, name_tag.
    """
    log.info(f"Stage 1: bulk index → name pre-filter ({start_date} → {end_date})")

    quarters = quarters_for_range(start_date, end_date)
    log.info(f"Quarters to fetch: {quarters}")

    all_rows: list[dict] = []
    for year, q in quarters:
        idx_text = fetch_form_idx(year, q)
        if not idx_text:
            log.warning(f"  {year} QTR{q}: empty index, skipping")
            continue
        rows = parse_form_idx(idx_text)
        log.info(f"  {year} QTR{q}: {len(rows)} Form D rows")
        all_rows.extend(rows)

    log.info(f"Total Form D rows across quarters: {len(all_rows)}")

    in_range = [r for r in all_rows if start_date <= r["filed_at"] <= end_date]
    log.info(f"After date-range filter: {len(in_range)}")

    classified: list[dict] = []
    skipped = 0
    for r in in_range:
        tag = classify_company_name(r["company_name"])
        if tag is None:
            skipped += 1
            continue
        r["name_tag"] = tag
        classified.append(r)

    clear_n = sum(1 for r in classified if r["name_tag"] == "clear_startup")
    ambig_n = sum(1 for r in classified if r["name_tag"] == "ambiguous")
    log.info(
        f"Stage 1 result: {len(classified)} kept "
        f"({clear_n} clear_startup, {ambig_n} ambiguous), "
        f"{skipped} dropped as noise"
    )
    return classified


# ── Stage 2: XML fetch + parse + filter (with progressive save) ──────────────

def fetch_formd_xml(cik: str, accession_no: str) -> Optional[str]:
    """
    Fetch the Form D primary document XML for (cik, accession_no).
    Tries primary_doc.xml first, then {accession-nodashes}.xml as a fallback.
    """
    cik_clean = str(int(cik)) if cik.strip().isdigit() else cik.strip()
    acc_clean = accession_no.replace("-", "").strip()

    for xml_filename in ["primary_doc.xml", f"{acc_clean}.xml"]:
        xml_url = f"{EDGAR_BASE_URL}/Archives/edgar/data/{cik_clean}/{acc_clean}/{xml_filename}"
        xml_text = _get(xml_url, as_json=False)
        if xml_text and "<edgarSubmission" in xml_text:
            return xml_text

    log.warning(f"  Could not find XML for {accession_no}")
    return None


def fetch_formd_xml_via_submissions(cik: str) -> list[dict]:
    """
    Utility: list all Form D filings for a single CIK via data.sec.gov.
    Not used by the main two-stage pipeline.
    """
    cik_padded = str(cik).zfill(10)
    url = f"{EDGAR_DATA_URL}/submissions/CIK{cik_padded}.json"
    data = _get(url, as_json=True)
    if not data:
        return []

    filings    = data.get("filings", {}).get("recent", {})
    forms      = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates      = filings.get("filingDate", [])

    return [
        {"form_type": form, "accession_no": acc, "filed_at": date}
        for form, acc, date in zip(forms, accessions, dates)
        if form in ("D", "D/A")
    ]


def parse_formd_xml(xml_content: str) -> Optional[dict]:
    """
    Parse a Form D XML filing into a flat dict of all useful fields.
    Handles both the old (pre-2009) and current XML schema.
    """
    if not xml_content or not xml_content.strip():
        return None

    try:
        root = etree.fromstring(
            xml_content.encode() if isinstance(xml_content, str) else xml_content
        )
    except etree.XMLSyntaxError as e:
        log.warning(f"XML parse error: {e}")
        return None

    def get(el, path, default=""):
        if el is None:
            return default
        found = el.find(path)
        return found.text.strip() if found is not None and found.text else default

    def to_int(val):
        try:
            v = str(val).replace(",", "").strip()
            return int(float(v)) if v else None
        except:
            return None

    issuer   = root.find("primaryIssuer")
    offering = root.find("offeringData")

    company_name   = get(issuer, "entityName")
    cik            = get(issuer, "cik")
    city           = get(issuer, "issuerAddress/city")
    state          = get(issuer, "issuerAddress/stateOrCountry")
    zip_code       = get(issuer, "issuerAddress/zipCode")
    phone          = get(issuer, "issuerPhoneNumber")
    jurisdiction   = get(issuer, "jurisdictionOfInc")
    entity_type    = get(issuer, "entityType")
    year_of_inc    = get(issuer, "yearOfInc/value")
    within_5_years = get(issuer, "yearOfInc/withinFiveYears")

    persons = []
    for p in root.findall(".//relatedPersonInfo"):
        first = get(p, "relatedPersonName/firstName")
        last  = get(p, "relatedPersonName/lastName")
        name  = f"{first} {last}".strip()
        roles = [r.text for r in p.findall(".//relationship") if r.text]
        if name:
            persons.append({"name": name, "roles": roles})

    industry        = get(offering, "industryGroup/industryGroupType")
    revenue_range   = get(offering, "issuerSize/revenueRange")
    date_first_sale = get(offering, "typeOfFiling/dateOfFirstSale/value")
    is_amendment    = get(offering, "typeOfFiling/newOrAmendment/isAmendment")
    more_than_1yr   = get(offering, "durationOfOffering/moreThanOneYear")

    exemptions = [el.text for el in root.findall(".//federalExemptionsExclusions/item") if el.text]

    type_map = {
        "isEquityType":             "Equity",
        "isDebtType":               "Debt",
        "isOptionToAcquireType":    "Option",
        "isPooledInvestmentFundType": "Pooled Fund",
        "isOtherType":              "Other",
    }
    sec_types = []
    if offering is not None:
        for tag, label in type_map.items():
            el = offering.find(f"typesOfSecuritiesOffered/{tag}")
            if el is not None and el.text and el.text.lower() == "true":
                sec_types.append(label)

    total_offering_raw = get(offering, "offeringSalesAmounts/totalOfferingAmount")
    total_sold_raw     = get(offering, "offeringSalesAmounts/totalAmountSold")
    clarification      = get(offering, "offeringSalesAmounts/clarificationOfResponse")

    total_offering = to_int(total_offering_raw) if total_offering_raw not in ("0", "", "Indefinite") else None
    total_sold     = to_int(total_sold_raw)
    is_indefinite  = "indefinite" in total_offering_raw.lower() if total_offering_raw else False

    num_investors      = get(offering, "investors/totalNumberAlreadyInvested")
    has_non_accredited = get(offering, "investors/hasNonAccreditedInvestors")

    round_size = total_sold or total_offering
    stage = _infer_stage(round_size, is_indefinite)

    return {
        "cik":                  cik,
        "company_name":         company_name,
        "city":                 city,
        "state":                state,
        "zip":                  zip_code,
        "phone":                phone,
        "jurisdiction_of_inc":  jurisdiction,
        "entity_type":          entity_type,
        "year_of_inc":          year_of_inc,
        "incorporated_within_5yrs": within_5_years,
        "industry":             industry,
        "revenue_range":        revenue_range,
        "date_of_first_sale":   date_first_sale,
        "is_amendment":         is_amendment,
        "duration_over_1yr":    more_than_1yr,
        "exemption_rules":      ", ".join(exemptions),
        "security_types":       ", ".join(sec_types),
        "total_offering_amount": total_offering,
        "total_amount_sold":     total_sold,
        "is_indefinite_amount":  is_indefinite,
        "offering_clarification": clarification,
        "num_investors":         num_investors,
        "has_non_accredited":    has_non_accredited,
        "inferred_stage":        stage,
        "related_persons":       persons,
        "exec_names":            "; ".join(p["name"] for p in persons),
    }


def _infer_stage(round_size: Optional[int], is_indefinite: bool) -> str:
    """Heuristic stage label from offering amount."""
    if is_indefinite or round_size is None:
        return "seed/unknown"
    if round_size < 500_000:
        return "pre-seed"
    if round_size < 3_000_000:
        return "seed"
    if round_size < 15_000_000:
        return "series_a"
    if round_size < 40_000_000:
        return "series_b"
    if round_size < 100_000_000:
        return "series_c"
    return "growth/late"


# ── Filters ───────────────────────────────────────────────────────────────────
KEEP_INDUSTRIES = {
    "Technology", "Other Technology", "Computers", "Internet",
    "Health Care", "Biotechnology", "Pharmaceuticals",
    "Business Services", "Finance", "Other",
}

EXCLUDED_INDUSTRIES = {
    "Pooled Investment Fund", "Real Estate", "Commercial",
    "Residential", "Construction", "Agriculture", "Mining",
    "Oil and Gas", "Restaurants", "Travel",
}

EXCLUDED_JURISDICTIONS = {
    "IRELAND", "CAYMAN ISLANDS", "VIRGIN ISLANDS, BRITISH",
    "ONTARIO", "ALBERTA", "BRITISH COLUMBIA", "ONTARIO, CANADA",
    "BRITISH COLUMBIA, CANADA", "ALBERTA, CANADA",
    "CANADA (FEDERAL LEVEL)", "QUEBEC", "SASKATCHEWAN, CANADA",
    "MANITOBA, CANADA", "NOVA SCOTIA, CANADA",
    "UNITED KINGDOM", "AUSTRALIA", "SINGAPORE", "HONG KONG",
    "LUXEMBOURG", "NETHERLANDS", "BERMUDA", "BAHAMAS",
}

# EDGAR state codes for foreign-province issuers we want to drop
# regardless of how jurisdiction_of_inc is spelled.
# A1 = British Columbia
EXCLUDED_STATES = {"A1"}

def passes_filters(record: dict) -> tuple[bool, str]:
    """
    Returns (True, "") if record passes all filters.
    Returns (False, reason) if it should be excluded.
    """
    if record.get("is_amendment", "").lower() == "true":
        return False, "amendment"

    industry = record.get("industry", "")
    if industry in EXCLUDED_INDUSTRIES:
        return False, f"industry={industry}"

    jurisdiction = record.get("jurisdiction_of_inc", "").upper()
    if jurisdiction in EXCLUDED_JURISDICTIONS:
        return False, f"foreign={jurisdiction}"

    state = record.get("state", "").upper()
    if state in EXCLUDED_STATES:
        return False, f"foreign_state={state}"

    amount_sold = record.get("total_amount_sold")
    if amount_sold is not None:
        if amount_sold < 100_000:
            return False, f"amount_too_small=${amount_sold:,}"
        if amount_sold > 100_000_000:
            return False, f"amount_too_large=${amount_sold:,}"

    date_str = record.get("date_of_first_sale", "")
    if date_str:
        try:
            year = int(date_str[:4])
            if year < 2018:
                return False, f"too_old={date_str}"
        except:
            pass

    return True, ""


# ── Stage 2 driver ────────────────────────────────────────────────────────────
def stage2_xml_fetch(
    candidates: list[dict],
    output_path: str = "formd_output.json",
    save_every: int = 50,
) -> list[dict]:
    """
    Stage 2: for each candidate from Stage 1, fetch primary_doc.xml,
    parse it, run passes_filters, and save progressively to output_path
    every `save_every` accepted records.
    """
    sorted_candidates = sorted(
        candidates,
        key=lambda r: 0 if r.get("name_tag") == "clear_startup" else 1,
    )
    total = len(sorted_candidates)
    log.info(f"Stage 2: processing {total} candidates "
             "(clear_startup first, then ambiguous)")

    out_path = Path(output_path)
    parsed: list[dict] = []
    fetch_failed = 0
    parse_failed = 0
    filtered     = 0

    for i, c in enumerate(sorted_candidates):
        cik  = c.get("cik", "")
        acc  = c.get("accession_no", "")
        name = c.get("company_name", "")
        tag  = c.get("name_tag", "")

        log.info(f"[{i+1}/{total}] [{tag}] {name} (CIK {cik})")

        if not cik or not acc:
            log.warning("  Missing CIK or accession; skipping")
            fetch_failed += 1
            continue

        xml = fetch_formd_xml(cik, acc)
        if not xml:
            fetch_failed += 1
            continue

        record = parse_formd_xml(xml)
        if not record:
            log.warning(f"  Parse failed for {acc}")
            parse_failed += 1
            continue

        record["filed_at"]     = c.get("filed_at", "")
        record["accession_no"] = acc
        record["form_type"]    = "D"
        record["name_tag"]     = tag
        if not record.get("company_name"):
            record["company_name"] = name

        keep, reason = passes_filters(record)
        if not keep:
            log.info(f"  ✗ FILTERED ({reason})")
            filtered += 1
            continue

        parsed.append(record)
        amount = record.get("total_amount_sold")
        amt_str = f"${amount:,}" if amount else "amount unknown"
        log.info(f"  ✓ {record['company_name']} | {record['inferred_stage']} | {amt_str}")

        if len(parsed) % save_every == 0:
            _save_json(parsed, out_path)
            log.info(f"  💾 Progress saved ({len(parsed)} records)")

    _save_json(parsed, out_path)
    csv_path = out_path.with_suffix(".csv")
    _save_csv(parsed, csv_path)

    _print_summary(parsed, total, fetch_failed, parse_failed, filtered, out_path, csv_path)
    return parsed


def _save_json(records: list[dict], path: Path):
    with open(path, "w") as f:
        json.dump(records, f, indent=2, default=str)


def _save_csv(records: list[dict], path: Path):
    """Save flat CSV (excludes nested related_persons list)."""
    if not records:
        return
    flat_keys = [k for k in records[0].keys() if k != "related_persons"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=flat_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _print_summary(parsed, total, fetch_failed, parse_failed, filtered, json_path, csv_path):
    log.info("=" * 60)
    log.info("Run summary")
    log.info("=" * 60)
    log.info(f"Total candidates fetched: {total}")
    log.info(f"  fetch failures:         {fetch_failed}")
    log.info(f"  parse failures:         {parse_failed}")
    log.info(f"  filtered out:           {filtered}")
    log.info(f"  passed filters:         {len(parsed)}")

    stage_counts: dict[str, int] = {}
    for r in parsed:
        s = r.get("inferred_stage", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1
    log.info("Breakdown by inferred_stage:")
    for s, n in sorted(stage_counts.items(), key=lambda x: -x[1]):
        log.info(f"  {s:20s} {n}")

    log.info(f"JSON: {json_path.resolve()}")
    log.info(f"CSV:  {csv_path.resolve()}")


# ── Pipeline orchestrator ─────────────────────────────────────────────────────
def scrape_formd(
    start_date: str,
    end_date: str,
    max_filings: Optional[int] = None,
    output_path: str = "formd_output.json",
) -> list[dict]:
    """
    End-to-end: Stage 1 (bulk index + name pre-filter) → Stage 2 (XML + parse + filter).

    Args:
        start_date:   "YYYY-MM-DD"
        end_date:     "YYYY-MM-DD"
        max_filings:  optional cap on Stage 2 candidates (for test runs).
                      Applied after sorting clear_startup first.
        output_path:  where to write JSON output (CSV written alongside).
    """
    log.info("=" * 60)
    log.info("EDGAR Form D Scraper (two-stage)")
    log.info(f"Date range: {start_date} → {end_date}")
    if max_filings:
        log.info(f"Max Stage 2 candidates: {max_filings}")
    log.info("=" * 60)

    candidates = stage1_bulk_filter(start_date, end_date)
    if not candidates:
        log.error("Stage 1 produced no candidates.")
        return []

    if max_filings:
        candidates = sorted(
            candidates,
            key=lambda r: 0 if r.get("name_tag") == "clear_startup" else 1,
        )[:max_filings]
        log.info(f"Capped Stage 2 candidates to {max_filings}")

    return stage2_xml_fetch(candidates, output_path=output_path)


# ── CLI entrypoint ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape SEC EDGAR Form D filings (two-stage)")
    parser.add_argument("--start",  default=(datetime.today() - timedelta(days=7)).strftime("%Y-%m-%d"))
    parser.add_argument("--end",    default=datetime.today().strftime("%Y-%m-%d"))
    parser.add_argument("--max",    type=int, default=None,
                        help="Optional cap on Stage 2 candidates (default: no cap)")
    parser.add_argument("--output", default="formd_output.json")
    args = parser.parse_args()

    results = scrape_formd(
        start_date=args.start,
        end_date=args.end,
        max_filings=args.max,
        output_path=args.output,
    )

    print(f"\n{'='*60}")
    print(f"Sample output ({min(3, len(results))} of {len(results)} records):")
    print('='*60)
    for r in results[:3]:
        print(json.dumps({k: v for k, v in r.items() if k != "related_persons"}, indent=2))
