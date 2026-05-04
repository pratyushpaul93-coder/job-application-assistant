#!/usr/bin/env python3
"""
Capture the actual API calls Getro's job board makes.

We use Playwright (headless Chromium) to load jobs.accel.com/companies,
wait for the page to fully load, and log every XHR/fetch call. This will
reveal the true API endpoint we need to hit.

Setup (one-time on VPS):
    pip3 install playwright --break-system-packages
    playwright install chromium
    playwright install-deps   # if needed

Usage:
    python3 getro_capture_xhr.py 2>&1 | tee /root/pp-jobapp/workspace/getro_xhr.log
"""

import json
from playwright.sync_api import sync_playwright

BOARDS = [
    ("accel",            "https://jobs.accel.com/companies"),
    ("general_catalyst", "https://jobs.generalcatalyst.com/companies"),
    ("lightspeed",       "https://jobs.lsvp.com/companies"),
    ("greylock",         "https://jobs.greylock.com/companies"),
]


def capture(label, url):
    print(f"\n{'='*70}")
    print(f"  {label}: {url}")
    print('='*70)

    api_calls = []  # tuples: (method, url, status, response_preview)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Hook into responses
        def on_response(response):
            req = response.request
            url_lower = response.url.lower()
            # We only care about XHR/fetch to API-shaped URLs
            if req.resource_type in ("xhr", "fetch"):
                # Filter out analytics, fonts, images
                if any(skip in url_lower for skip in [
                    "analytics", "sentry", "googletagmanager",
                    "google-analytics", "doubleclick", "/fonts/",
                    ".woff", ".png", ".jpg", ".svg", ".css", ".js",
                ]):
                    return

                ct = response.headers.get("content-type", "")
                preview = ""
                if "json" in ct.lower():
                    try:
                        body = response.text()
                        preview = body[:400]
                    except Exception:
                        preview = "(could not read)"

                api_calls.append({
                    "method": req.method,
                    "url": response.url,
                    "status": response.status,
                    "content_type": ct,
                    "preview": preview,
                })

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  navigation error: {e}")

        # Wait an extra moment for any lazy fetches
        page.wait_for_timeout(3000)

        browser.close()

    print(f"  Captured {len(api_calls)} API calls\n")

    for i, call in enumerate(api_calls):
        print(f"  [{i+1}] {call['method']} {call['status']} "
              f"({call['content_type'][:30]})")
        print(f"       {call['url']}")
        if call["preview"]:
            preview_clean = call["preview"].replace("\n", " ")[:300]
            print(f"       body: {preview_clean}")
        print()


for label, url in BOARDS:
    try:
        capture(label, url)
    except Exception as e:
        print(f"  ERROR on {label}: {e}")
