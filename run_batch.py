#!/usr/bin/env python3
"""
Batch runner for web_scraper.scrape()
Usage: python run_batch.py
Reads `urls.txt`, scrapes each URL, saves per-URL JSON into `output/` and a combined `all_results.json`.
"""
import os
import json
import time
import sys
import re
from urllib.parse import urlparse

try:
    from web_scraper import scrape
except Exception as e:
    print("Error importing web_scraper.scrape():", e)
    sys.exit(1)

URL_FILE = "urls.txt"
OUTPUT_DIR = "output"
DELAY = 1.2

os.makedirs(OUTPUT_DIR, exist_ok=True)


def safe_filename_from_url(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "").strip("/")
    base = path if path else p.netloc
    if p.query:
        base = base + "_" + p.query
    # replace invalid filename characters
    name = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not name:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", p.netloc)
    return name + ".json"


all_results = []

with open(URL_FILE, "r", encoding="utf-8") as f:
    urls = [line.strip() for line in f if line.strip()]

print(f"Loaded {len(urls)} URLs from {URL_FILE}")

for idx, url in enumerate(urls, start=1):
    print(f"\n[{idx}/{len(urls)}] Scraping: {url}")
    try:
        data = scrape(url)
    except Exception as e:
        print(f"❌ Error scraping {url}: {e}")
        continue

    fname = safe_filename_from_url(url)
    out_path = os.path.join(OUTPUT_DIR, fname)
    with open(out_path, "w", encoding="utf-8") as of:
        json.dump(data, of, ensure_ascii=False, indent=2)
    print(f"✅ Saved: {out_path}")
    all_results.append({"url": url, "file": out_path, "project_name": data.get("project_name")})

    time.sleep(DELAY)

combined_path = os.path.join(OUTPUT_DIR, "all_results.json")
with open(combined_path, "w", encoding="utf-8") as cf:
    json.dump(all_results, cf, ensure_ascii=False, indent=2)

print(f"\nDone. {len(all_results)} successful scrapes. Combined index: {combined_path}")
