# -*- coding: utf-8 -*-
"""มูลค่ายุติธรรมและกรอบราคา (โซนซื้อ / ราคาทบทวนขาย)

วิธีที่ 1  ปันผลคิดลด (Gordon):   FV = D0 × (1+g) / (r − g)
วิธีที่ 2  กรอบอัตราปันผลในอดีต:   FV = D0 / อัตราปันผลเฉลี่ย 5 ปีของตัวเอง
D0 = ปันผลเฉลี่ยต่อปีของ N ปีเต็มล่าสุด (ลดผลจากปันผลพิเศษปีเดียว)
"""
from .util import mean


def fair_value(m, cfg):
    f = cfg["fair_value"]
    r = f["required_return_pct"] / 100.0
    g = f["long_term_div_growth_pct"] / 100.0
    d0 = m.get("d0")
    out = {"fv_ddm": None, "fv_yield_band": None, "fair_value": None,
           "buy_price": None, "trim_price": None, "upside_pct": None, "fv_note": ""}
    if not d0 or d0 <= 0:
        out["fv_note"] = "ไม่มีปันผลพอคำนวณ"
        return out
    if r > g:
        out["fv_ddm"] = d0 * (1 + g) / (r - g)
    else:
        out["fv_note"] = "ค่า r ต้องมากกว่า g"
    if m.get("avg_yield_5y_pct"):
        out["fv_yield_band"] = d0 / (m["avg_yield_5y_pct"] / 100.0)

    cands = [v for v in (out["fv_ddm"], out["fv_yield_band"]) if v]
    method = f.get("method", "blend")
    if method == "dividend_discount":
        fv = out["fv_ddm"]
    elif method == "yield_band":
        fv = out["fv_yield_band"] or out["fv_ddm"]
    elif method == "min_of_both":
        fv = min(cands) if cands else None
    else:  # blend
        fv = mean(cands)
    if not fv:
        return out
    out["fair_value"] = fv
    out["buy_price"] = fv * (1 - f["margin_of_safety_buy_pct"] / 100.0)
    out["trim_price"] = fv * (1 + f["premium_trim_pct"] / 100.0)
    if m.get("price"):
        out["upside_pct"] = (fv / m["price"] - 1) * 100
    return out
