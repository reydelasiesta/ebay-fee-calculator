"""Live USPS zone lookup for an arbitrary origin/destination ZIP pair.

Calls USPS's own public "Get Zone for ZIP Code Pair" tool
(https://postcalc.usps.com/DomesticZoneChart/Index) instead of baking in a
zone chart for one fixed origin -- this is what makes the shipping estimator
work for any ship-from ZIP, including a seller who uses more than one.

Results are cached to disk (data/zone_lookup_cache.json) since USPS's zone
charts only change a handful of times a year -- no need to hit their server
again for a pair already looked up recently.
"""
import json
import re
import threading
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_PATH = DATA_DIR / "zone_lookup_cache.json"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days -- USPS zone charts change quarterly at most
MAX_CACHE_ENTRIES = 5000

USPS_ENDPOINT = "https://postcalc.usps.com/DomesticZoneChart/GetZone"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://postcalc.usps.com/DomesticZoneChart/Index",
}

_lock = threading.Lock()


def _load_cache():
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def _parse_zone_info(html_fragment):
    text = re.sub(r"<[^>]*>", " ", html_fragment)
    text = re.sub(r"\s+", " ", text).strip()
    zone_match = re.search(r"Zone is (\d+)", text)
    zone = int(zone_match.group(1)) if zone_match else None
    is_local = "This is a Local Zone" in text
    same_ndc = "is within the same NDC" in text
    return {
        "zone": zone,
        "is_local": is_local,
        "same_ndc_as_origin": same_ndc,
        "message": text,
    }


def get_zone(origin_zip, destination_zip):
    """Look up the USPS zone between origin_zip and destination_zip.

    Returns {"zone": int|None, "is_local": bool, "same_ndc_as_origin": bool,
    "message": str, "effective_date": str|None, "error": str|None, "cached": bool}.
    """
    origin_zip = (origin_zip or "").strip()
    destination_zip = (destination_zip or "").strip()

    if not re.match(r"^\d{5}$", origin_zip) or not re.match(r"^\d{5}$", destination_zip):
        return {"error": "Both ZIP codes must be 5 digits.", "zone": None}

    cache_key = f"{origin_zip}:{destination_zip}"

    with _lock:
        cache = _load_cache()
        entry = cache.get(cache_key)
        if entry and (time.time() - entry["fetched_at"]) < CACHE_TTL_SECONDS:
            result = dict(entry["result"])
            result["cached"] = True
            return result

    try:
        resp = requests.get(
            USPS_ENDPOINT,
            params={
                "origin": origin_zip,
                "destination": destination_zip,
                "shippingDate": datetime.now(timezone.utc).strftime("%m/%d/%Y"),
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        return {"error": f"USPS lookup failed: {e}", "zone": None}

    if data.get("OriginError") or data.get("DestinationError") or data.get("PageError"):
        err = data.get("OriginError") or data.get("DestinationError") or data.get("PageError")
        return {"error": err, "zone": None}

    result = _parse_zone_info(data.get("ZoneInformation", ""))
    result["effective_date"] = data.get("EffectiveDate")
    result["error"] = None
    result["cached"] = False

    with _lock:
        cache = _load_cache()
        cache[cache_key] = {"fetched_at": time.time(), "result": {k: v for k, v in result.items() if k != "cached"}}
        if len(cache) > MAX_CACHE_ENTRIES:
            oldest_keys = sorted(cache, key=lambda k: cache[k]["fetched_at"])[: len(cache) - MAX_CACHE_ENTRIES]
            for k in oldest_keys:
                del cache[k]
        _save_cache(cache)

    return result
