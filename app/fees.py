"""Fee schedule loading and eBay fee/profit calculation."""
import json
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FEES_PATH = DATA_DIR / "fees.json"

_lock = threading.Lock()
_fees_cache = None


def load_fees(force=False):
    global _fees_cache
    with _lock:
        if _fees_cache is None or force:
            with open(FEES_PATH, "r", encoding="utf-8") as f:
                _fees_cache = json.load(f)
        return _fees_cache


def list_categories():
    fees = load_fees()
    return [
        {"key": key, "label": cat["label"], "verified": cat.get("verified", False)}
        for key, cat in fees["categories"].items()
    ]


def _apply_brackets(brackets, amount):
    """Tiered fee: each bracket's pct applies only to the slice of `amount` in its range."""
    total = 0.0
    remaining = amount
    lower = 0.0
    for bracket in brackets:
        upto = bracket["upto"]
        pct = bracket["pct"]
        if upto is None:
            slice_amount = remaining
        else:
            slice_amount = max(0.0, min(remaining, upto - lower))
            lower = upto
        total += slice_amount * (pct / 100.0)
        remaining -= slice_amount
        if remaining <= 0:
            break
    return total


def _resolve_category_tier(category, store_tier):
    """Return (tier_data, estimated: bool) for a category+tier, falling back to
    most_categories when this category has no data for the requested tier."""
    lookup_tier = "none" if store_tier == "starter" else store_tier
    tier_data = category.get(lookup_tier)
    if tier_data is not None:
        return tier_data, False
    fallback = load_fees()["categories"]["most_categories"].get(lookup_tier)
    return fallback, True


def calculate(
    category_key,
    store_tier,
    sale_price,
    shipping_charged=0.0,
    shipping_cost=0.0,
    item_cost=0.0,
    other_costs=0.0,
    is_international=False,
    promoted_pct=0.0,
    below_standard=False,
    insertion_fee_override=0.0,
):
    fees = load_fees()
    if category_key not in fees["categories"]:
        raise ValueError(f"Unknown category: {category_key}")
    category = fees["categories"][category_key]

    tier_data, estimated = _resolve_category_tier(category, store_tier)
    if tier_data is None:
        raise ValueError(f"No fee data available for category '{category_key}'")

    revenue = sale_price + shipping_charged

    final_value_fee = _apply_brackets(tier_data["brackets"], revenue)

    if below_standard:
        surcharge_pct = fees["below_standard_surcharge_pct"]["standard"]
        below_standard_fee = revenue * (surcharge_pct / 100.0)
    else:
        below_standard_fee = 0.0

    no_per_order_fee = category.get("no_per_order_fee", False)
    if no_per_order_fee:
        per_order_fee = 0.0
    else:
        po = fees["per_order_fee"]
        per_order_fee = po["at_or_below"] if revenue <= po["threshold"] else po["above"]

    international_fee = revenue * (fees["international_fee_pct"] / 100.0) if is_international else 0.0
    promoted_fee = revenue * (promoted_pct / 100.0) if promoted_pct else 0.0

    total_ebay_fees = (
        final_value_fee
        + per_order_fee
        + international_fee
        + promoted_fee
        + below_standard_fee
        + insertion_fee_override
    )

    net_proceeds = revenue - total_ebay_fees
    total_costs = item_cost + shipping_cost + other_costs
    profit = net_proceeds - total_costs

    return {
        "revenue": round(revenue, 2),
        "fees": {
            "final_value_fee": round(final_value_fee, 2),
            "per_order_fee": round(per_order_fee, 2),
            "international_fee": round(international_fee, 2),
            "promoted_listings_fee": round(promoted_fee, 2),
            "below_standard_surcharge": round(below_standard_fee, 2),
            "insertion_fee": round(insertion_fee_override, 2),
            "total": round(total_ebay_fees, 2),
        },
        "net_proceeds": round(net_proceeds, 2),
        "total_costs": round(total_costs, 2),
        "profit": round(profit, 2),
        "margin_pct": round((profit / sale_price) * 100, 2) if sale_price else 0.0,
        "roi_pct": round((profit / item_cost) * 100, 2) if item_cost else None,
        "category_rate_estimated": estimated,
        "fee_schedule_last_verified": fees["meta"]["last_verified"],
    }
