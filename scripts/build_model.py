"""
NFLX pitch model — produces deck_data.json consumed by the HTML deck.

All quantitative output in the deck comes from this script. Per Jackson's
scripted-analysis rule, the LLM never computes numbers.

Inputs:
  data/nflx_companyfacts.json   SEC XBRL company facts (10-K reported figures)
  Manual: regional ARPU + sub counts (from the 10-K/Q text — pulled by hand
          into the SEGMENTS dict below, sourced and dated)

Outputs:
  data/deck_data.json           keys consumed by dashboard.html / deck.html
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


# ------------------------- 1. Historical financials ------------------------- #
def load_annual_fact(facts: dict, key: str, alt_keys: list[str] | None = None) -> dict[int, float]:
    """Return {fy: usd_value} for true annual (start=Jan1, end=Dec31) 10-K facts.

    XBRL companyfacts repeats each fact for every filing in which it appeared as
    a comparative. We pick rows where start..end is the full fiscal year and we
    key by end-year so we never confuse a comparative for a current-period fact.
    """
    keys = [key] + (alt_keys or [])
    for k in keys:
        node = facts.get("us-gaap", {}).get(k)
        if not node:
            continue
        out: dict[int, tuple[float, str]] = {}
        for v in node["units"]["USD"]:
            if v.get("form") not in ("10-K", "10-K/A"):
                continue
            start = v.get("start", "")
            end = v.get("end", "")
            if not (start.endswith("-01-01") and end.endswith("-12-31")):
                continue
            fy = int(end[:4])
            filed = v.get("filed", "")
            # latest filing wins (restatements)
            if fy not in out or filed > out[fy][1]:
                out[fy] = (v["val"], filed)
        return {fy: vt[0] for fy, vt in out.items()}
    return {}


def load_eop_fact(facts: dict, key: str) -> dict[int, float]:
    """End-of-period balance-sheet item, keyed by fiscal year."""
    node = facts.get("us-gaap", {}).get(key)
    if not node:
        return {}
    out: dict[int, tuple[float, str]] = {}
    for v in node["units"]["USD"]:
        if v.get("form") not in ("10-K", "10-K/A"):
            continue
        end = v.get("end", "")
        if not end.endswith("-12-31"):
            continue
        fy = int(end[:4])
        filed = v.get("filed", "")
        if fy not in out or filed > out[fy][1]:
            out[fy] = (v["val"], filed)
    return {fy: vt[0] for fy, vt in out.items()}


def build_historicals() -> dict:
    facts = json.loads((DATA / "nflx_companyfacts.json").read_text())["facts"]
    rev = load_annual_fact(facts, "Revenues")
    cor = load_annual_fact(facts, "CostOfRevenue")
    mk_old = load_annual_fact(facts, "MarketingExpense")
    mk_new = load_annual_fact(facts, "SellingAndMarketingExpense")
    mk = {**mk_old, **mk_new}                       # newer tag wins
    ga = load_annual_fact(facts, "GeneralAndAdministrativeExpense")
    rd = load_annual_fact(facts, "ResearchAndDevelopmentExpense")
    op = load_annual_fact(facts, "OperatingIncomeLoss")
    ni = load_annual_fact(facts, "NetIncomeLoss")
    debt = load_eop_fact(facts, "LongTermDebtNoncurrent")
    cash = load_eop_fact(facts, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")
    equity = load_eop_fact(facts, "StockholdersEquity")
    assets = load_eop_fact(facts, "Assets")

    years = sorted(y for y in rev if y >= 2018 and y in op)
    hist = []
    for fy in years:
        r = rev[fy]
        row = {
            "fy": fy,
            "revenue": r,
            "cost_of_revenue": cor.get(fy),
            "marketing": mk.get(fy),
            "ga": ga.get(fy),
            "rd": rd.get(fy),
            "operating_income": op.get(fy),
            "net_income": ni.get(fy),
            "long_term_debt": debt.get(fy),
            "cash": cash.get(fy),
            "equity": equity.get(fy),
            "total_assets": assets.get(fy),
            "ebit_margin": op.get(fy) / r if op.get(fy) is not None else None,
            "content_cost_pct": cor.get(fy) / r if cor.get(fy) is not None else None,
            "marketing_pct": mk.get(fy) / r if mk.get(fy) is not None else None,
        }
        hist.append(row)
    return hist


# --------------------- 2. Operating segments (sub + ARPU) ------------------- #
# Source: NFLX FY2024 10-K, page F-12 (regional rev / paid memberships).
# Netflix discontinued reporting paid memberships and ARM by region after Q4
# 2024, but the FY24 10-K is the most recent disclosed breakdown.
# FY25 totals from FY25 10-K filed 2026-01-23.
SEGMENTS = {
    "FY2024": {
        "ucan": {"revenue": 17359e6, "members": 89.6e6, "arm": 17.26},      # US/Canada
        "emea": {"revenue": 13693e6, "members": 101.0e6, "arm": 11.39},
        "latam": {"revenue": 4886e6,  "members": 53.3e6,  "arm": 7.69},
        "apac": {"revenue": 4061e6,   "members": 57.5e6,  "arm": 7.31},
    },
    "FY2025": {
        "total_revenue": 45180e6,
        "total_paid_memberships_est": 325e6,  # mgmt commentary, end-2025
    },
}


# ------------------- 3. Forward-projection scenarios ------------------------ #
# Anchored to mgmt's 2026 guide: $50.7-51.7B revenue (12-14% growth), 31.5%
# op margin including ~$275M of acq-related costs (so 32%+ clean).
# 2025 actual: $45.18B revenue, 29.5% EBIT margin per mgmt commentary.
BASE_FY25 = {"revenue": 45180e6, "ebit_margin": 0.295, "ebit": 13328e6}

# Each scenario is a 5-year ramp from FY26 to FY30.
SCENARIOS = {
    "no_deal_base": {
        "label": "No deal — base case",
        "growth": [0.135, 0.125, 0.115, 0.105, 0.095],          # rev growth
        "ebit_margin": [0.315, 0.335, 0.350, 0.360, 0.370],      # op margin
        "wbd_pricing_uplift": 0.0,
        "extra_debt": 0,
    },
    "no_deal_bull": {
        "label": "No deal — bull case",
        "growth": [0.140, 0.140, 0.130, 0.120, 0.110],
        "ebit_margin": [0.320, 0.345, 0.365, 0.380, 0.395],
        "wbd_pricing_uplift": 0.0,
        "extra_debt": 0,
    },
    "wbd_deal_base": {
        "label": "WBD deal at Paramount-match terms",
        "growth": [0.135, 0.125, 0.115, 0.105, 0.095],
        "ebit_margin": [0.310, 0.330, 0.350, 0.365, 0.380],     # slight near-term margin hit from integration
        "wbd_pricing_uplift": 0.10,                              # 10% price uplift starts FY28
        "wbd_uplift_start_fy": 2028,
        "wbd_drop_through": 0.98,                                # 98% of incremental price → EBIT
        "extra_debt": 71.2e9,                                    # incremental debt to fund deal
    },
    "wbd_deal_bear": {
        "label": "WBD deal — integration drag",
        "growth": [0.125, 0.115, 0.105, 0.095, 0.085],
        "ebit_margin": [0.290, 0.305, 0.325, 0.345, 0.360],
        "wbd_pricing_uplift": 0.05,
        "wbd_uplift_start_fy": 2028,
        "wbd_drop_through": 0.85,
        "extra_debt": 91.2e9,                                    # paying more than Paramount
    },
}


def project_scenario(scn: dict) -> list[dict]:
    rev = BASE_FY25["revenue"]
    out = []
    for i, g in enumerate(scn["growth"]):
        fy = 2026 + i
        rev = rev * (1.0 + g)
        # apply WBD pricing uplift
        uplift_rev = 0.0
        uplift_ebit = 0.0
        if scn.get("wbd_pricing_uplift") and fy >= scn.get("wbd_uplift_start_fy", 9999):
            uplift_rev = rev * scn["wbd_pricing_uplift"]
            uplift_ebit = uplift_rev * scn["wbd_drop_through"]
        total_rev = rev + uplift_rev
        base_ebit = rev * scn["ebit_margin"][i]
        total_ebit = base_ebit + uplift_ebit
        out.append({
            "fy": fy,
            "revenue": total_rev,
            "core_revenue": rev,
            "uplift_revenue": uplift_rev,
            "ebit": total_ebit,
            "core_ebit": base_ebit,
            "uplift_ebit": uplift_ebit,
            "ebit_margin": total_ebit / total_rev,
            "growth": (total_rev / (out[-1]["revenue"] if out else BASE_FY25["revenue"])) - 1,
        })
    return out


# ------------------------------- 4. Valuation ------------------------------- #
# Valuation framework: 5yr EBIT x exit multiple - debt + interim FCF.
SHARES_OUT = 4344e6 / 1000  # mil shares already, store as 4.344B float
# Note: VIC writeup quotes 4,344M shares; we use 4.344B.
SHARES = 4.344e9
CURRENT_PRICE = 83.00        # post-10:1 split (Nov 17 2025); $360B mkt cap / 4.344B sh
EXISTING_NET_DEBT = 7.908e9  # VIC: $7.908B; matches our extracted ~$8B
EBIT_TO_FCF_CONVERSION = 0.80
TAX_RATE = 0.22              # blended after-tax not used (we frame on EBIT)
EXIT_MULTIPLE = 17.0         # forward EV/EBIT applied to FY30 EBIT


def value_scenario(scn_key: str, proj: list[dict]) -> dict:
    scn = SCENARIOS[scn_key]
    exit_ebit = proj[-1]["ebit"]
    exit_ev = exit_ebit * EXIT_MULTIPLE
    # interim FCF (FY26-FY28): EBIT * 0.80 conversion
    interim_fcf = sum(p["ebit"] * EBIT_TO_FCF_CONVERSION for p in proj[:3])
    debt = EXISTING_NET_DEBT + scn["extra_debt"]
    equity_value = exit_ev + interim_fcf - debt
    target_price = equity_value / SHARES
    irr_4yr = (target_price / CURRENT_PRICE) ** (1 / 4) - 1
    return {
        "scenario": scn_key,
        "label": scn["label"],
        "exit_ebit": exit_ebit,
        "exit_ev": exit_ev,
        "interim_fcf": interim_fcf,
        "debt": debt,
        "equity_value": equity_value,
        "target_price": target_price,
        "current_price": CURRENT_PRICE,
        "upside_pct": (target_price / CURRENT_PRICE - 1),
        "irr_4yr": irr_4yr,
    }


# ------------- 5. Sensitivity: exit multiple x FY30 EBIT margin ------------- #
def sensitivity(proj: list[dict]) -> dict:
    multiples = [13, 15, 17, 19, 21]
    fy30_rev = proj[-1]["revenue"]
    margins = [0.32, 0.35, 0.38, 0.40, 0.42]
    grid = []
    for mg in margins:
        row = []
        for mult in multiples:
            exit_ev = fy30_rev * mg * mult
            interim_fcf = sum(p["ebit"] * EBIT_TO_FCF_CONVERSION for p in proj[:3])
            equity = exit_ev + interim_fcf - EXISTING_NET_DEBT
            px = equity / SHARES
            irr = (px / CURRENT_PRICE) ** (1 / 4) - 1
            row.append({"px": px, "irr": irr, "ev": exit_ev})
        grid.append({"margin": mg, "row": row})
    return {"multiples": multiples, "margins": margins, "grid": grid}


# ----------------------------- 6. Peer comps -------------------------------- #
# Hand-curated from public consensus (mid-May 2026), rounded; explicit so the
# numbers can be audited / refreshed in one place.
PEERS = [
    {"ticker": "NFLX", "name": "Netflix",            "mkt_cap_b": 360.5, "ev_b": 368.4, "ev_ebit_26": 22.6, "ev_ebit_27": 18.8, "rev_growth_26": 0.135, "ebit_margin_26": 0.315, "fcf_yield_26": 0.030},
    {"ticker": "DIS",  "name": "Disney",             "mkt_cap_b": 173.0, "ev_b": 213.0, "ev_ebit_26": 13.5, "ev_ebit_27": 12.0, "rev_growth_26": 0.040, "ebit_margin_26": 0.155, "fcf_yield_26": 0.060},
    {"ticker": "WBD",  "name": "Warner Bros Discovery","mkt_cap_b": 79.0,  "ev_b": 116.0, "ev_ebit_26": 11.5, "ev_ebit_27": 10.0, "rev_growth_26": 0.005, "ebit_margin_26": 0.090, "fcf_yield_26": 0.050},
    {"ticker": "PARA", "name": "Paramount",          "mkt_cap_b": 19.5,  "ev_b": 33.0,  "ev_ebit_26": 14.0, "ev_ebit_27": 11.5, "rev_growth_26": -0.020, "ebit_margin_26": 0.070, "fcf_yield_26": 0.040},
    {"ticker": "SPOT", "name": "Spotify",            "mkt_cap_b": 130.0, "ev_b": 126.0, "ev_ebit_26": 27.0, "ev_ebit_27": 21.0, "rev_growth_26": 0.145, "ebit_margin_26": 0.135, "fcf_yield_26": 0.025},
    {"ticker": "GOOGL","name": "Alphabet (YouTube)", "mkt_cap_b": 2200.0,"ev_b": 2150.0,"ev_ebit_26": 17.5, "ev_ebit_27": 15.0, "rev_growth_26": 0.110, "ebit_margin_26": 0.320, "fcf_yield_26": 0.040},
    {"ticker": "META", "name": "Meta",               "mkt_cap_b": 1500.0,"ev_b": 1475.0,"ev_ebit_26": 14.5, "ev_ebit_27": 12.5, "rev_growth_26": 0.165, "ebit_margin_26": 0.420, "fcf_yield_26": 0.045},
]


# ------------------------------ 7. Assemble --------------------------------- #
def main() -> None:
    hist = build_historicals()
    proj = {k: project_scenario(v) for k, v in SCENARIOS.items()}
    valuations = {k: value_scenario(k, v) for k, v in proj.items()}
    sens = sensitivity(proj["wbd_deal_base"])

    # Long-run operating leverage: content cost % rev, mktg % rev, EBIT margin
    leverage_table = [
        {"fy": r["fy"], "content_pct": r["content_cost_pct"], "mkt_pct": r["marketing_pct"], "ebit_margin": r["ebit_margin"]}
        for r in hist if r["content_cost_pct"] is not None
    ]

    out = {
        "as_of": "2026-05-15",
        "ticker": "NFLX",
        "current_price": CURRENT_PRICE,
        "shares_out": SHARES,
        "existing_net_debt": EXISTING_NET_DEBT,
        "fy25_actual": BASE_FY25,
        "historicals": hist,
        "segments_fy24": SEGMENTS["FY2024"],
        "fy25_summary": SEGMENTS["FY2025"],
        "scenarios": {
            k: {
                "label": SCENARIOS[k]["label"],
                "extra_debt": SCENARIOS[k]["extra_debt"],
                "projection": proj[k],
                "valuation": valuations[k],
            }
            for k in SCENARIOS
        },
        "sensitivity": sens,
        "peers": PEERS,
        "operating_leverage": leverage_table,
        "assumptions": {
            "exit_multiple_fwd_ev_ebit": EXIT_MULTIPLE,
            "ebit_to_fcf": EBIT_TO_FCF_CONVERSION,
            "wbd_pricing_uplift_base": SCENARIOS["wbd_deal_base"]["wbd_pricing_uplift"],
            "wbd_drop_through": SCENARIOS["wbd_deal_base"]["wbd_drop_through"],
        },
    }

    (DATA / "deck_data.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote deck_data.json — {len(hist)} historical years, "
          f"{len(SCENARIOS)} scenarios, {len(PEERS)} peers.")
    # quick visibility
    for k, v in valuations.items():
        print(f"  {k:18s}  target ${v['target_price']:7.0f}  upside {v['upside_pct']*100:+.1f}%  IRR {v['irr_4yr']*100:5.1f}%")


if __name__ == "__main__":
    main()
