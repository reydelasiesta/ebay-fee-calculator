"""Periodic check that eBay's published fee pages still match data/fees.json.

This never auto-modifies fees.json. It fetches eBay's fee pages, strips them to
plain text, and looks for each category/fee's stored `anchor_text` snippet
verbatim. If a snippet is missing, that row is flagged as possibly stale --
a human needs to re-check eBay's page and update fees.json by hand. This is a
deliberate design choice: silently trusting a scrape to rewrite numbers that
drive real profit math is exactly the kind of thing to avoid.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from fees import load_fees, FEES_PATH

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_PATH = DATA_DIR / "fee_check_log.jsonl"
PENDING_PATH = DATA_DIR / "pending_fee_updates.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch_text(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def _normalize(s):
    return re.sub(r"\s+", " ", s).strip()


def run_check():
    fees = load_fees(force=True)
    sources = fees["meta"]["source_urls"]

    combined_text = ""
    fetch_errors = []
    any_fetch_succeeded = False
    for url in sources:
        try:
            combined_text += " " + _normalize(_fetch_text(url))
            any_fetch_succeeded = True
        except Exception as e:
            fetch_errors.append({"url": url, "error": str(e)})

    findings = []

    def check(label, anchor_text):
        if not anchor_text:
            return
        ok = _normalize(anchor_text) in combined_text
        findings.append({"label": label, "anchor_text": anchor_text, "still_present": ok})

    if not any_fetch_succeeded:
        # Every source failed -- don't report every anchor as "stale", that would
        # blame eBay's content when the real problem is we couldn't fetch it.
        result = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
            "fetch_errors": fetch_errors,
            "checked_count": 0,
            "stale_count": 0,
            "stale_findings": [],
            "fetch_failed_entirely": True,
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")
        with open(PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        return result

    check("per_order_fee", fees["per_order_fee"].get("anchor_text"))
    check("international_fee", fees.get("international_fee_anchor_text"))
    check("insertion_fee", fees["insertion_fee"].get("anchor_text"))
    check("below_standard_surcharge", fees["below_standard_surcharge_pct"].get("anchor_text"))

    for key, cat in fees["categories"].items():
        for tier in ("none", "basic_plus"):
            tier_data = cat.get(tier)
            if tier_data:
                check(f"{key}.{tier}", tier_data.get("anchor_text"))

    stale = [f for f in findings if not f["still_present"]]

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "fetch_errors": fetch_errors,
        "checked_count": len(findings),
        "stale_count": len(stale),
        "stale_findings": stale,
    }

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(result) + "\n")

    if stale or fetch_errors:
        with open(PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    elif PENDING_PATH.exists():
        PENDING_PATH.unlink()

    return result


if __name__ == "__main__":
    print(json.dumps(run_check(), indent=2))
