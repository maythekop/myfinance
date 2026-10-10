# -*- coding: utf-8 -*-
"""ให้คะแนน 0-100 แบบเปอร์เซ็นไทล์ในกลุ่มอุตสาหกรรม (ปรับน้ำหนักได้จาก settings)"""

# ชื่อใน settings → (ฟิลด์ใน metrics, ทิศทาง: +1 สูงดี / -1 ต่ำดี / 0 คิดแบบช่วงเหมาะสม)
METRIC_MAP = {
    "div_yield": ("div_yield_pct", 1),
    "div_consistency": ("div_years_10y", 1),
    "payout_sustainability": ("payout_pct", 0),
    "pe": ("pe", -1),
    "pbv": ("pbv", -1),
    "yield_vs_5y_avg": ("yield_vs_5y_avg", 1),
    "roe": ("roe_pct", 1),
    "net_margin": ("net_margin_pct", 1),
    "eps_stability": ("eps_stability", 1),
    "de_ratio": ("de_x", -1),
    "current_ratio": ("current_ratio", 1),
    "free_cashflow": ("fcf_yield_pct", 1),
}

PILLAR_TH = {"dividend": "ปันผล", "valuation": "มูลค่า", "quality": "คุณภาพ", "strength": "ความแข็งแรง"}


def _valid(field, v):
    if v is None:
        return False
    if field == "pe" and v <= 0:
        return False
    return True


def percentile(v, values):
    n = len(values)
    if n <= 1:
        return 50.0
    less = sum(1 for x in values if x < v)
    eq = sum(1 for x in values if x == v)
    return (less + 0.5 * (eq - 1)) / (n - 1) * 100.0


def payout_score(p, cfg):
    lo, hi = cfg["scoring"]["payout_sweet_spot_pct"]
    mx = cfg["hard_filters"]["max_payout_ratio_pct"]
    if p <= 0:
        return 0.0
    if p < lo:
        return 100.0 * p / lo
    if p <= hi:
        return 100.0
    return max(0.0, 100.0 * (mx - p) / (mx - hi)) if mx > hi else 0.0


def score_all(rows, cfg):
    sc = cfg["scoring"]
    min_peers = sc.get("min_peers_for_sector_percentile", 4)

    peer_vals = {}
    for key, (field, _) in METRIC_MAP.items():
        allv, by_sec = [], {}
        for r in rows:
            v = r.get(field)
            if _valid(field, v):
                allv.append(v)
                by_sec.setdefault(r["sector"], []).append(v)
        peer_vals[key] = (allv, by_sec)

    for r in rows:
        pillars = {}
        for pillar, mweights in cfg["metric_weights"].items():
            tot_w, acc = 0.0, 0.0
            for key, w in mweights.items():
                field, direction = METRIC_MAP[key]
                v = r.get(field)
                if not _valid(field, v) or w <= 0:
                    continue
                if direction == 0:
                    s = payout_score(v, cfg)
                else:
                    allv, by_sec = peer_vals[key]
                    peers = by_sec.get(r["sector"], [])
                    if sc.get("method") != "percentile_in_sector" or len(peers) < min_peers:
                        peers = allv
                    s = percentile(v, peers)
                    if direction < 0:
                        s = 100.0 - s
                acc += s * w
                tot_w += w
            pillars[pillar] = acc / tot_w if tot_w else None

        pw = cfg["pillar_weights"]
        used = {p: s for p, s in pillars.items() if s is not None and pw.get(p, 0) > 0}
        wsum = sum(pw[p] for p in used)
        r["pillar_scores"] = {p: (round(s, 1) if s is not None else None) for p, s in pillars.items()}
        r["score"] = round(sum(s * pw[p] for p, s in used.items()) / wsum, 1) if wsum else None
        total_w = sum(v for v in pw.values() if v > 0)
        r["data_completeness_pct"] = round(100.0 * wsum / total_w) if total_w else 0
    return rows
