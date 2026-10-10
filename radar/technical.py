# -*- coding: utf-8 -*-
"""ตัวชี้วัดจังหวะ: SMA, RSI (Wilder), ระยะจากจุดต่ำ/สูงรอบ 52 สัปดาห์, แนวโน้ม, ATR และ Chandelier Exit"""


def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def rsi(xs, n=14):
    if len(xs) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def compute(close_pairs, cfg):
    t = cfg["timing_technical"]
    xs = [c for _, c in close_pairs]
    out = {"last_close": None, "sma_short": None, "sma_long": None, "rsi": None,
           "high_52w": None, "low_52w": None, "from_low_pct": None, "from_high_pct": None,
           "trend": "ไม่มีข้อมูล", "price_date": None}
    if not xs:
        return out
    last = xs[-1]
    yr = xs[-252:]
    out.update({
        "last_close": last, "price_date": close_pairs[-1][0],
        "sma_short": sma(xs, t["sma_short_days"]), "sma_long": sma(xs, t["sma_long_days"]),
        "rsi": rsi(xs[-300:], t["rsi_days"]),
        "high_52w": max(yr), "low_52w": min(yr),
    })
    out["from_low_pct"] = (last / out["low_52w"] - 1) * 100 if out["low_52w"] else None
    out["from_high_pct"] = (last / out["high_52w"] - 1) * 100 if out["high_52w"] else None
    s, l = out["sma_short"], out["sma_long"]
    if s and l:
        if last > l and s > l:
            out["trend"] = "ขาขึ้น"
        elif last < l and s < l:
            out["trend"] = "ขาลง"
        else:
            out["trend"] = "ไซด์เวย์"
    return out


# ---------------------------------------------------------------------------
# ATR และ Chandelier Exit (เส้นตามแนวโน้มที่ปรับระยะตามความผันผวนของหุ้นแต่ละตัว)
#   ATR             = ค่าเฉลี่ยแบบ Wilder ของ true range = max(สูง−ต่ำ, |สูง−ปิดก่อนหน้า|, |ต่ำ−ปิดก่อนหน้า|)
#   เส้นตัดขาดทุน   = ราคาสูงสุด n แท่ง − k × ATR   (ขาขึ้น: ปิดต่ำกว่าเส้นนี้ = แนวโน้มจบ)
#   เส้นกลับตัว     = ราคาต่ำสุด n แท่ง + k × ATR   (ขาลง: ปิดเหนือเส้นนี้ = กลับเป็นขาขึ้น)
#   เส้นขยับได้ทางเดียว (ขาขึ้นไม่ลดลง ขาลงไม่เพิ่มขึ้น) แบบเดียวกับ TradingView
# แท่ง (bar) = [วันที่, สูง, ต่ำ, ปิด]
# ---------------------------------------------------------------------------
def weekly_bars(bars):
    """รวมแท่งรายวันเป็นรายสัปดาห์ (จันทร์–ศุกร์ ตามสัปดาห์ ISO) สัปดาห์ล่าสุดอาจยังไม่ครบ"""
    import datetime as _dt
    out, key = [], None
    for d, h, l, c in bars:
        y, w, _ = _dt.date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
        if (y, w) != key:
            out.append([d, h, l, c])
            key = (y, w)
        else:
            b = out[-1]
            b[0], b[1], b[2], b[3] = d, max(b[1], h), min(b[2], l), c
    return out


def atr_list(bars, n):
    """ATR ของทุกแท่ง (None จนกว่าจะครบ n แท่ง)"""
    trs, out, a = [], [], None
    for i, (_, h, l, c) in enumerate(bars):
        tr = h - l if i == 0 else max(h - l, abs(h - bars[i - 1][3]), abs(l - bars[i - 1][3]))
        trs.append(tr)
        if i + 1 == n:
            a = sum(trs) / n
        elif i + 1 > n:
            a = (a * (n - 1) + tr) / n
        out.append(a)
    return out


def chandelier(bars, n=22, k=3.0):
    """ผลล่าสุดของ Chandelier Exit: ทิศ (1 ขาขึ้น / −1 ขาลง), เส้นตัดขาดทุน, เส้นกลับตัว,
    จำนวนแท่งตั้งแต่เปลี่ยนทิศ และ ATR ล่าสุด · คืน None ถ้าข้อมูลไม่พอ"""
    if len(bars) < n + 2:
        return None
    atr = atr_list(bars, n)
    ls_prev = ss_prev = None
    d, flip = 1, 0
    for i in range(n - 1, len(bars)):
        hh = max(b[1] for b in bars[i - n + 1:i + 1])
        ll = min(b[2] for b in bars[i - n + 1:i + 1])
        ls, ss = hh - k * atr[i], ll + k * atr[i]
        c, pc = bars[i][3], bars[i - 1][3]
        if ls_prev is not None:
            if pc > ls_prev:
                ls = max(ls, ls_prev)
            if pc < ss_prev:
                ss = min(ss, ss_prev)
            nd = 1 if c > ss_prev else (-1 if c < ls_prev else d)
            flip = 0 if nd != d else flip + 1
            d = nd
        ls_prev, ss_prev = ls, ss
    return {"dir": d, "long_stop": ls_prev, "short_stop": ss_prev, "flip_bars": flip, "atr": atr[-1]}


def compute_trend_stops(bars, cfg):
    """ค่าที่ส่งเข้าผลวิเคราะห์: Chandelier รายวัน (จังหวะซื้อ) + รายสัปดาห์ (ดูแลหุ้นที่ถือยาว)"""
    t = cfg["timing_technical"]
    out = {"atr": None, "atr_pct": None, "ce_dir": None, "ce_long_stop": None, "ce_short_stop": None,
           "ce_flip_bars": None, "cew_dir": None, "cew_long_stop": None, "cew_short_stop": None, "cew_flip_bars": None}
    if not bars:
        return out
    dly = chandelier(bars, int(t.get("atr_days", 22)), float(t.get("chandelier_mult", 3.0)))
    if dly:
        out.update(atr=dly["atr"], atr_pct=dly["atr"] / bars[-1][3] * 100 if bars[-1][3] else None,
                   ce_dir=dly["dir"], ce_long_stop=dly["long_stop"], ce_short_stop=dly["short_stop"],
                   ce_flip_bars=dly["flip_bars"])
    wk = chandelier(weekly_bars(bars), int(t.get("chandelier_weekly_weeks", 22)), float(t.get("chandelier_weekly_mult", 3.0)))
    if wk:
        out.update(cew_dir=wk["dir"], cew_long_stop=wk["long_stop"], cew_short_stop=wk["short_stop"],
                   cew_flip_bars=wk["flip_bars"])
    return out


def bars_from_close(close_pairs):
    """ไม่มีราคาสูง/ต่ำ (ข้อมูลรุ่นเก่า) → ใช้ราคาปิดแทน ATR จะเป็นช่วงห่างของราคาปิด"""
    return [[d, c, c, c] for d, c in close_pairs]
