# -*- coding: utf-8 -*-
"""คำนวณตัวชี้วัดพื้นฐานและด่านคัดออก"""
from collections import defaultdict
from datetime import datetime

from .util import mean, num, std

FINANCIAL_SECTORS = ("Financial Services",)


def _annual(pairs, agg="sum"):
    by = defaultdict(list)
    for d, v in pairs:
        by[int(d[:4])].append(v)
    if agg == "sum":
        return {y: sum(vs) for y, vs in by.items()}
    return {y: sum(vs) / len(vs) for y, vs in by.items()}


def compute_metrics(raw, cfg, today):
    info = raw.get("info") or {}
    divs = raw.get("dividends") or []
    close = raw.get("close") or []
    ni = [v for v in (raw.get("net_income") or []) if v is not None]
    fv_cfg = cfg["fair_value"]

    price = num(info.get("currentPrice")) or num(info.get("regularMarketPrice"))
    if price is None and close:
        price = close[-1][1]

    mcap = num(info.get("marketCap"))
    sector = info.get("sector") or "ไม่ระบุ"
    is_fin = sector in FINANCIAL_SECTORS

    # ---------- ปันผล ----------
    ann_div = _annual(divs, "sum")
    ann_px = _annual(close, "mean")
    last_full = today.year - 1
    div_years_10y = sum(1 for y in range(last_full - 9, last_full + 1) if ann_div.get(y, 0) > 0) if divs else 0

    cutoff = datetime(today.year - 1, today.month, min(today.day, 28)).strftime("%Y-%m-%d")
    ttm_div = sum(v for d, v in divs if d > cutoff)
    div_yield = ttm_div / price * 100 if (price and divs) else None
    if div_yield is None:
        dy = num(info.get("dividendYield"))
        if dy is not None:
            div_yield = dy if dy > 1 else dy * 100  # yfinance บางรุ่นคืนเป็น % บางรุ่นเป็นสัดส่วน

    yearly_yield = []
    for y in range(last_full - 4, last_full + 1):
        if ann_px.get(y) and y in ann_div:
            yearly_yield.append(ann_div[y] / ann_px[y] * 100)
    avg_yield_5y = mean(yearly_yield) if len(yearly_yield) >= 3 else None
    yield_vs_avg = div_yield / avg_yield_5y if (div_yield is not None and avg_yield_5y) else None

    base_n = int(fv_cfg.get("dividend_base_years", 3))
    base_years = [ann_div.get(y, 0.0) for y in range(last_full - base_n + 1, last_full + 1)]
    d0 = mean(base_years) if divs else None

    last_div, prev_div = ann_div.get(last_full), ann_div.get(last_full - 1)
    cut_pct = cfg["timing_signal"].get("dividend_cut_pct", 20)
    dividend_cut = bool(prev_div and last_div is not None and last_div < prev_div * (1 - cut_pct / 100.0))

    payout = num(info.get("payoutRatio"))
    payout = payout * 100 if payout is not None else None

    # ---------- มูลค่า ----------
    pe = num(info.get("trailingPE"))
    eps = num(info.get("trailingEps"))
    if pe is None and price and eps:
        pe = price / eps if eps > 0 else -1.0
    pbv = num(info.get("priceToBook"))
    bv = num(info.get("bookValue"))
    if pbv is None and price and bv and bv > 0:
        pbv = price / bv

    # ---------- คุณภาพ ----------
    roe = num(info.get("returnOnEquity"))
    roe = roe * 100 if roe is not None else None
    nm = num(info.get("profitMargins"))
    nm = nm * 100 if nm is not None else None
    profitable_years = sum(1 for v in ni if v > 0)
    eps_stability = None
    if len(ni) >= 3:
        if any(v <= 0 for v in ni):
            eps_stability = 0.0
        else:
            eps_stability = 1.0 / (1.0 + std(ni) / mean(ni))

    # ---------- ความแข็งแรง ----------
    de = num(info.get("debtToEquity"))
    de = de / 100 if de is not None else None  # Yahoo รายงานเป็น % (85 = 0.85 เท่า)
    cr = num(info.get("currentRatio"))
    fcf = num(info.get("freeCashflow"))
    fcf_yield = fcf / mcap * 100 if (fcf is not None and mcap) else None
    if is_fin:
        de, cr, fcf_yield = None, None, None

    avg_vol = num(info.get("averageVolume"))
    turnover_mb = avg_vol * price / 1e6 if (avg_vol and price) else None

    m = {
        "ticker": raw["ticker"],
        "name": info.get("shortName") or info.get("longName") or raw["ticker"],
        "sector": sector, "industry": info.get("industry") or "", "is_financial": is_fin,
        "price": price, "market_cap_mb": mcap / 1e6 if mcap else None, "turnover_mb": turnover_mb,
        "ttm_div": ttm_div if divs else None, "div_yield_pct": div_yield, "div_years_10y": div_years_10y, "avg_yield_5y_pct": avg_yield_5y,
        "yield_vs_5y_avg": yield_vs_avg, "d0": d0, "last_year_div": last_div, "prev_year_div": prev_div,
        "dividend_cut": dividend_cut, "payout_pct": payout,
        "pe": pe, "pbv": pbv, "roe_pct": roe, "net_margin_pct": nm,
        "eps_stability": eps_stability, "income_years": len(ni), "profitable_years": profitable_years,
        "de_x": de, "current_ratio": cr, "fcf_yield_pct": fcf_yield,
    }
    m["filter_fails"] = hard_filter(m, cfg)
    m["passed_filters"] = not m["filter_fails"]
    return m


def hard_filter(m, cfg):
    u, h = cfg["universe"], cfg["hard_filters"]
    fails = []
    if m["price"] is None:
        return ["ไม่มีราคา"]
    if m["ticker"] in (u.get("exclude_tickers") or []):
        fails.append("อยู่ในรายการยกเว้น")
    if m["market_cap_mb"] is not None and m["market_cap_mb"] < u["min_market_cap_mb"]:
        fails.append("มูลค่าตลาดต่ำกว่าเกณฑ์")
    if m["turnover_mb"] is not None and m["turnover_mb"] < u["min_avg_turnover_mb"]:
        fails.append("สภาพคล่องต่ำ")
    if m["div_years_10y"] < h["min_dividend_years_of_last_10"]:
        fails.append("จ่ายปันผล %d ใน 10 ปี (เกณฑ์ %d)" % (m["div_years_10y"], h["min_dividend_years_of_last_10"]))
    need = min(h["min_profitable_years_of_last_4"], m["income_years"])
    if m["income_years"] and m["profitable_years"] < need:
        fails.append("มีปีที่ขาดทุน")
    if m["payout_pct"] is not None and m["payout_pct"] > h["max_payout_ratio_pct"]:
        fails.append("จ่ายปันผลเกินกำไร (payout %.0f%%)" % m["payout_pct"])
    if m["de_x"] is not None and m["de_x"] > h["max_de_ratio"] and (not m["is_financial"] or h.get("apply_de_to_financials")):
        fails.append("หนี้สูง (D/E %.2f เท่า)" % m["de_x"])
    if m["pe"] is not None and (m["pe"] <= 0 or m["pe"] > h["max_pe"]):
        fails.append("P/E ไม่อยู่ในเกณฑ์" if m["pe"] > 0 else "กำไรติดลบ")
    return fails
