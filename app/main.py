import json
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import fees as fee_engine
import fee_checker
import zone_lookup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ebay-fee-calculator")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

app = FastAPI(title="eBay Fee & Profit Calculator")


class CalculateRequest(BaseModel):
    category_key: str
    store_tier: str = "none"
    sale_price: float
    shipping_charged: float = 0.0
    shipping_cost: float = 0.0
    item_cost: float = 0.0
    other_costs: float = 0.0
    is_international: bool = False
    promoted_pct: float = 0.0
    below_standard: bool = False
    insertion_fee_override: float = 0.0


@app.get("/api/categories")
def get_categories():
    return {
        "categories": fee_engine.list_categories(),
        "store_tiers": fee_engine.load_fees()["store_tiers"],
        "fee_schedule_last_verified": fee_engine.load_fees()["meta"]["last_verified"],
    }


@app.post("/api/calculate")
def calculate(req: CalculateRequest):
    try:
        return fee_engine.calculate(**req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calculate/bulk")
def calculate_bulk():
    # Framework placeholder for a future CSV bulk-import iteration.
    # Planned shape: accept a CSV upload, run each row through fee_engine.calculate,
    # return a CSV/JSON of results. Not implemented yet.
    raise HTTPException(status_code=501, detail="Bulk CSV import is not implemented yet.")


@app.get("/api/fee-status")
def fee_status():
    pending_path = DATA_DIR / "pending_fee_updates.json"
    pending = None
    if pending_path.exists():
        with open(pending_path, "r", encoding="utf-8") as f:
            pending = json.load(f)
    return {
        "last_verified": fee_engine.load_fees()["meta"]["last_verified"],
        "pending_review": pending,
    }


@app.post("/api/admin/check-now")
def check_now():
    return fee_checker.run_check()


@app.get("/api/shipping-rates")
def shipping_rates():
    with open(DATA_DIR / "shipping_rates.json", "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/zone-lookup")
def zone_lookup_endpoint(origin: str, destination: str):
    result = zone_lookup.get_zone(origin, destination)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


scheduler = BackgroundScheduler()


@app.on_event("startup")
def start_scheduler():
    def safe_check():
        try:
            result = fee_checker.run_check()
            if result["stale_count"] or result["fetch_errors"]:
                logger.warning("Fee check found issues: %s", result)
            else:
                logger.info("Fee check passed, all anchors present.")
        except Exception:
            logger.exception("Weekly fee check failed")

    scheduler.add_job(safe_check, "interval", weeks=1, id="weekly_fee_check")
    scheduler.start()
