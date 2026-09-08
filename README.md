# eBay Fee & Profit Calculator

Self-hosted single-item eBay fee/profit calculator. Runs as one Docker container,
no external accounts, API keys, or paid services required.

## What it calculates

Given a sale price, shipping charged/paid, item cost, and a few optional toggles
(international buyer, Promoted Listings ad rate, Below Standard surcharge), it
returns eBay's final value fee (tiered by category and Store subscription tier),
the per-order fee, and your net profit/margin/ROI.

Fee data lives in `data/fees.json`, seeded directly from eBay's own published
fee pages:
- https://www.ebay.com/help/selling/fees-credits-invoices/selling-fees?id=4822
- https://www.ebay.com/help/selling/selling-fees/store-fees?id=4809

Categories marked `"verified": false`, or with a `null` entry for a given store
tier, aren't individually confirmed against eBay's page — those fall back to
the "most categories" rate as a labeled estimate (the UI flags this).

## Staying accurate over time

eBay changes fees periodically. Rather than scraping and silently rewriting
`fees.json` (a bad idea for numbers that drive real profit math), a background
job (`app/fee_checker.py`, runs on startup and weekly via APScheduler) re-fetches
the two source pages above and checks whether each stored fee's exact wording
(`anchor_text` in fees.json) still appears verbatim. If eBay's wording/numbers
changed, the check can't blindly tell *what* changed — it flags it for manual
review:

- `data/pending_fee_updates.json` is written with what no longer matched.
- The web UI shows a banner if this file exists.
- `data/fee_check_log.jsonl` keeps a running history of every check.
- `POST /api/admin/check-now` runs a check on demand.

When flagged, re-read the relevant eBay page yourself and update `fees.json`
by hand — this tool deliberately never auto-applies scraped numbers.

## Explanations & Key panel

The right-side panel in the UI is a glossary (COGS, Final Value Fee, Below
Standard seller performance, INAD rate, Promoted Listings, etc.) plus an
"eBay gotchas" list of need-to-know behavior that isn't obvious from the fee
schedule alone (e.g. free shipping doesn't lower your fees, you're fee'd on
sales tax too, Store subscription cost isn't amortized into this calculator).
Content is static in `static/index.html` — update it by hand if eBay's rules
change; it isn't covered by the automated fee_checker.

## Shipping Cost Estimator

An optional card that estimates shipping cost by carrier/service and fills
the "Your actual shipping cost" field. Data lives in `data/shipping_rates.json`,
seeded from USPS Notice 123 (Postal Explorer):
- https://pe.usps.com/text/dmm300/Notice123.htm

Covers USPS Ground Advantage and Priority Mail (by zone + weight), Priority
Mail Flat Rate envelopes/boxes (flat, no zone), and Media Mail (by weight).
These are USPS **retail counter rates** — eBay-purchased or third-party labels
are usually cheaper. UPS Ground and FedEx Home Delivery are listed but not
computed: dimensional weight, account discounts, and fuel surcharges vary too
much to hardcode responsibly, so those entries just point you to the carrier's
own calculator instead of faking a precise number. This rate data is a
point-in-time snapshot, not covered by the weekly fee_checker.

### Automatic zone detection (works for any ship-from ZIP)

For zone-based services, entering **your ship-from ZIP** and **the buyer's
ZIP** auto-fills the correct USPS zone (still manually overridable). This is
a *live* lookup — `app/zone_lookup.py` queries USPS's own public
"Get Zone for ZIP Code Pair" tool (the same one at
https://postcalc.usps.com/DomesticZoneChart/Index) for that exact ZIP pair,
so it's correct for whatever ZIP you actually ship from, not a chart baked in
for one origin. Results are cached to `data/zone_lookup_cache.json` for 7 days
(USPS zone charts don't change often) so repeat lookups don't keep hitting
USPS. If you ship from more than one address, your recently-used ship-from
ZIPs are remembered per-browser (localStorage) so you can pick from a
dropdown instead of retyping — nothing server-side needs to know about your
multiple origins.

## Running it

```
docker compose up -d --build
```

Serves on `:8000` inside the container; the port exposed on the host is set
in `docker-compose.yml` (defaults to `8341` — change it to whatever's free on
your machine). `data/` is bind-mounted so `fees.json`, `shipping_rates.json`,
and the check/cache files persist across rebuilds.

## API

- `GET /api/categories` — categories, store tiers, last-verified date
- `POST /api/calculate` — single-item calculation (see `CalculateRequest` in `app/main.py` for fields)
- `POST /api/calculate/bulk` — stub, returns 501; reserved for a future CSV bulk-import iteration
- `GET /api/fee-status` — last-verified date + any pending review
- `POST /api/admin/check-now` — trigger a fee-schedule check immediately
- `GET /api/shipping-rates` — the shipping rate table backing the estimator
- `GET /api/zone-lookup?origin=XXXXX&destination=YYYYY` — live USPS zone for that ZIP pair (both 5-digit)

## Known limitations

- Not every eBay leaf category is modeled — only the ones eBay's fee page
  calls out individually. Everything else uses "most categories."
- The Below Standard surcharge is modeled as a flat +6% of order total, which
  is an approximation — eBay's own wording on how exactly it composes with
  tiered brackets is not fully unambiguous. Rarely-used toggle; verify against
  your own account if it applies.
- No login/auth — this is meant to run on a private network (home server,
  Tailscale, LAN) behind whatever access control you already have, not to be
  exposed directly to the public internet.
- The zone lookup depends on USPS's public tool staying at its current URL/
  response shape; if USPS changes it, `app/zone_lookup.py` will need updating.

## License

MIT — see `LICENSE`.
