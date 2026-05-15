# Netflix (NFLX) — Long-Only Investment Memo

A single-page HTML pitch deck for NFLX framed for a long-only large asset
manager. Built from SEC EDGAR primary filings, not LLM-imagined numbers.

By JAOD & (mainly) Claude.

**Live deck:** see GitHub Pages URL for this repo.

## Structure

```
index.html              the deck (15 slides, Chart.js, keyboard nav)
data/deck_data.json     all numerical content — produced by build_model.py
scripts/build_model.py  Python model that pulls XBRL company facts and emits
                        deck_data.json (no LLM-computed numbers)
```

## Method

Every quantitative claim in the deck traces to `data/deck_data.json`, which
is produced by `scripts/build_model.py`. The model pulls Netflix's
historical financials directly from SEC XBRL companyfacts (CIK 0001065280),
applies management's FY26 guide, and projects FY26E–FY30E under four
explicit scenarios (no-deal base / no-deal bull / WBD-deal base / WBD-deal
bear). Valuation = FY30 EBIT × 17× exit EV/EBIT + interim FCF − net debt,
discounted to current price for a 4-year IRR.

## Reproducing

```
python3 scripts/build_model.py   # regenerates data/deck_data.json
```

Then open `index.html` (or push to GitHub Pages).

## Sources

- Netflix 10-K filings FY2018–FY2025 (SEC EDGAR)
- Q4 2025 shareholder letter (Jan 20, 2026 8-K)
- Eagle Capital Q2 2023 investor letter (Distribution-is-Defense framework)
- Peer consensus multiples — mid-May 2026 sell-side rollup
