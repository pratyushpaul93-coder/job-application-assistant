#!/usr/bin/env python3
"""Ingest Built In "Best Places to Work" award lists.

Each list URL is a page like:
    https://builtin.com/awards/<geo>/<year>/best-<segment>-places-to-work
    https://builtin.com/awards/<geo>/<year>/best-places-to-work           (segment = overall)

Companies on a list are server-rendered into the static HTML — no JS execution
needed. We parse name, position, industry tags, employees, location, and founded
year from each company block.

A company that appears on multiple lists ends up with one company_sources row
whose raw_metadata.lists is the accumulated array, courtesy of
upsert_company_source_metadata + merge_keys=('lists',).

Usage:
    python3 -m ingest.builtin_bptw --list chicago/2025/best-startup-places-to-work
    python3 -m ingest.builtin_bptw --all
    python3 -m ingest.builtin_bptw --all --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Iterator
from urllib.request import Request, urlopen

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

from ingest.common import CompanyRecord, ingest_companies  # noqa: E402

SOURCE_TYPE = "builtin_bptw"
RAW_ROOT = Path("/root/pp-jobapp/workspace/data/external/builtin_bptw")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

GEOS = (
    "us", "remote",
    "atlanta", "austin", "boston", "chicago", "colorado", "dallas",
    "houston", "los-angeles", "miami", "new-york-city", "san-diego",
    "san-francisco", "seattle", "washington-dc",
)
SEGMENTS = (
    ("overall", "best-places-to-work"),
    ("startup", "best-startup-places-to-work"),
    ("midsize", "best-midsize-places-to-work"),
    ("large",   "best-large-places-to-work"),
)


def all_list_paths(year: str = "2025") -> list[str]:
    """Return all 64 list path-segments (geo/year/slug)."""
    return [f"{geo}/{year}/{slug}" for geo in GEOS for _, slug in SEGMENTS]


def segment_from_path(path: str) -> tuple[str, str, str]:
    """Parse 'chicago/2025/best-startup-places-to-work' -> (geo, year, size_segment)."""
    parts = path.strip("/").split("/")
    if len(parts) != 3:
        raise ValueError(f"Bad list path: {path!r}")
    geo, year, slug = parts
    for seg_name, seg_slug in SEGMENTS:
        if slug == seg_slug:
            return geo, year, seg_name
    raise ValueError(f"Unknown segment slug: {slug!r}")


def fetch(path: str) -> str:
    """Fetch a list page and cache the HTML in workspace/data/external/builtin_bptw/<date>/."""
    url = f"https://builtin.com/awards/{path}"
    cache_dir = RAW_ROOT / date.today().isoformat()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / (path.replace("/", "_") + ".html")
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", errors="replace")
    cache_path.write_text(html, encoding="utf-8")
    return html


_H2 = re.compile(
    r'<h2 class="title"><a href="/company/([a-z0-9-]+)"[^>]*>([^<]+)</a></h2>'
)
_INDUSTRY = re.compile(r'<div class="field-type">\s*([^<]+)</div>')
_EMPLOYEES = re.compile(r'Total Employees</div><div class="item">([^<]+)</div>')
_LOCATION = re.compile(
    r'field field-location[^>]*>.*?<div class="item">([^<]+)</div>', re.DOTALL
)
_FOUNDED = re.compile(r'datetime="(\d{4})-')


def _to_int(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip().replace(",", "")
    try:
        return int(s)
    except ValueError:
        return None


def _split_location(loc: str | None) -> tuple[str | None, str | None]:
    """'Chicago, IL + 1 office' -> ('Chicago', 'IL'). Remote-only -> (None, None)."""
    if not loc:
        return None, None
    head = loc.split("+", 1)[0].strip()
    if "," in head:
        city, state = (p.strip() for p in head.split(",", 1))
        return city or None, state or None
    return head or None, None


def parse(html: str, path: str) -> Iterator[CompanyRecord]:
    """Parse one list page into CompanyRecord stream."""
    geo, year, size_segment = segment_from_path(path)
    matches = list(_H2.finditer(html))
    positions = [m.start() for m in matches] + [len(html)]
    seen_slugs: set[str] = set()
    for i, m in enumerate(matches):
        slug, name = m.group(1), m.group(2).strip()
        if not name or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        seg = html[positions[i]:positions[i + 1]]
        industry = (_INDUSTRY.search(seg) or [None, None])
        industry_str = industry.group(1).strip() if industry else None
        industry_tags = [t.strip() for t in re.split(r"\s*\+\s*", industry_str)] if industry_str else []
        emp = _EMPLOYEES.search(seg)
        loc = _LOCATION.search(seg)
        founded = _FOUNDED.search(seg)
        city, state = _split_location(loc.group(1) if loc else None)
        employee_count = _to_int(emp.group(1) if emp else None)

        list_entry = {
            "list_slug": path,
            "geo": geo,
            "year": year,
            "size_segment": size_segment,
            "position": i + 1,  # position in HTML order; not necessarily public rank
            "builtin_slug": slug,
        }
        meta = {"lists": [list_entry]}
        if industry_tags:
            meta["industry_tags"] = industry_tags
        if founded:
            meta["founded"] = int(founded.group(1))

        yield CompanyRecord(
            canonical_name=name,
            raw_name=name,
            employee_count=employee_count,
            hq_city=city,
            hq_state=state,
            raw_metadata=meta,
        )


def ingest_list(path: str, *, year: str, dry_run: bool, verbose: bool) -> None:
    html = fetch(path)
    records = list(parse(html, path))
    if not records:
        print(f"  [WARN] no companies parsed from {path!r}")
        return
    summary = ingest_companies(
        records,
        source_type=SOURCE_TYPE,
        source_name=year,
        merge_keys=("lists",),
        one_row_per_company=True,
        dry_run=dry_run,
        verbose=verbose,
    )
    print(f"  {path:60s}  {len(records):>3} parsed  {summary}")


def main() -> None:
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--list", help='e.g. "chicago/2025/best-startup-places-to-work"')
    grp.add_argument("--all", action="store_true", help="iterate all 64 lists")
    ap.add_argument("--year", default="2025")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between list fetches in --all mode")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    paths = all_list_paths(args.year) if args.all else [args.list]
    mode = "DRY-RUN" if args.dry_run else "INGEST"
    print(f"[{mode}] builtin_bptw — {len(paths)} list(s)")
    for i, p in enumerate(paths, 1):
        try:
            ingest_list(p, year=args.year, dry_run=args.dry_run, verbose=args.verbose)
        except Exception as e:
            print(f"  [ERROR] {p}: {e}", file=sys.stderr)
        if args.all and i < len(paths):
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
