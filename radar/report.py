# -*- coding: utf-8 -*-
"""เขียนผลลัพธ์: results.json (ให้เว็บแอปอ่าน), results.csv (เปิดใน Sheets), report.md (อ่านเอง)"""
import csv
import json
import os
from collections import Counter

from .signals import ORDER
from .util import rnd

CSV_COLS = [
    "ticker", "name", "sector", "signal", "score", "price", "fair_value", "buy_price", "trim_price",
    "upside_pct", "div_yield_pct", "avg_yield_5y_pct", "pe", "pbv", "roe_pct", "de_x", "payout_pct",
    "div_years_10y", "rsi", "trend", "from_low_pct", "news_neg_severity", "data_completeness_pct",
    "reasons", "notes",
]


def _f(v, d=2):
    return "-" if v is None else ("{:,.%df}" % d).format(v)


def write_all(rows, outdir, meta):
    os.makedirs(outdir, exist_ok=True)
    rows = sorted(rows, key=lambda r: (ORDER.index(r["signal"]), -(r.get("score") or 0)))

    with open(os.path.join(outdir, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stocks": rows}, f, ensure_ascii=False, indent=1, default=str)

    with open(os.path.join(outdir, "results.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for r in rows:
            vals = []
            for c in CSV_COLS:
                v = r.get(c)
                if isinstance(v, list):
                    v = " | ".join(str(x) for x in v)
                elif isinstance(v, float):
                    v = rnd(v, 2)
                vals.append(v)
            w.writerow(vals)

    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write(render_md(rows, meta))
    return rows


def _tbl(rows, cols):
    head = "| " + " | ".join(c[0] for c in cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = "".join("| " + " | ".join(c[1](r) for c in cols) + " |\n" for r in rows)
    return head + body


def render_md(rows, meta):
    by = {}
    for r in rows:
        by.setdefault(r["signal"], []).append(r)
    L = []
    L.append("# Thai Stock Radar: รายงาน%s" % ("ประจำวัน" if meta["mode"] == "full" else "อัปเดตข่าวและราคา"))
    L.append("")
    L.append("อัปเดต: %s · หุ้นที่วิเคราะห์ %d ตัว · ประเมินข่าวด้วย: %s" % (meta["generated_at"], len(rows), meta.get("news_method", "-")))
    L.append("")
    counts = " · ".join("%s %d" % (s, len(by.get(s, []))) for s in ORDER)
    L.append("**สรุป:** " + counts)
    L.append("")

    if meta.get("macro"):
        L.append("## ภาวะตลาดโลก")
        L.append("")
        L.append(_tbl(meta["macro"], [
            ("ตัวแปร", lambda m: m["name"]), ("ล่าสุด", lambda m: _f(m["last"])),
            ("1 วัน", lambda m: "%+.2f%%" % m["chg_pct"]), ("5 วัน", lambda m: "%+.2f%%" % m["chg_5d_pct"])]))

    def notes(r):
        return "; ".join(r.get("notes") or []) or "-"

    if by.get("ซื้อ"):
        L.append("## สัญญาณซื้อ (ผ่านพื้นฐาน + ราคาอยู่ในโซนซื้อ)")
        L.append("")
        L.append(_tbl(by["ซื้อ"], [
            ("หุ้น", lambda r: "**%s**" % r["ticker"]), ("คะแนน", lambda r: _f(r["score"], 0)),
            ("ราคา", lambda r: _f(r["price"])), ("มูลค่ายุติธรรม", lambda r: _f(r["fair_value"])),
            ("ซื้อได้ไม่เกิน", lambda r: _f(r["buy_price"])), ("ส่วนต่าง", lambda r: "%+.1f%%" % r["upside_pct"]),
            ("ปันผล", lambda r: _f(r["div_yield_pct"], 1) + "%"), ("หมายเหตุจังหวะ", notes)]))

    if by.get("ทบทวนขาย"):
        L.append("## ทบทวนการขาย (ถ้าถือหุ้นตัวนี้อยู่)")
        L.append("")
        L.append(_tbl(by["ทบทวนขาย"], [
            ("หุ้น", lambda r: "**%s**" % r["ticker"]), ("ราคา", lambda r: _f(r["price"])),
            ("มูลค่ายุติธรรม", lambda r: _f(r.get("fair_value"))), ("เหตุผล", lambda r: "; ".join(r["reasons"]))]))

    if by.get("รอข่าวคลี่คลาย"):
        L.append("## อยู่ในโซนซื้อ แต่รอข่าวคลี่คลาย")
        L.append("")
        L.append(_tbl(by["รอข่าวคลี่คลาย"], [
            ("หุ้น", lambda r: "**%s**" % r["ticker"]), ("ราคา", lambda r: _f(r["price"])),
            ("ซื้อได้ไม่เกิน", lambda r: _f(r["buy_price"])),
            ("ข่าว", lambda r: (r["news_items"][0]["title"] if r.get("news_items") else "-"))]))

    if by.get("รอราคา"):
        L.append("## หุ้นดี รอราคา (ราคาเป้าหมายที่จะเริ่มซื้อ)")
        L.append("")
        L.append(_tbl(by["รอราคา"], [
            ("หุ้น", lambda r: r["ticker"]), ("คะแนน", lambda r: _f(r["score"], 0)),
            ("ราคา", lambda r: _f(r["price"])), ("ซื้อได้ไม่เกิน", lambda r: _f(r.get("buy_price"))),
            ("ต้องลงอีก", lambda r: ("%.1f%%" % ((1 - r["buy_price"] / r["price"]) * 100)) if r.get("buy_price") and r.get("price") else "-"),
            ("ปันผล", lambda r: _f(r["div_yield_pct"], 1) + "%"), ("แนวโน้ม", lambda r: r.get("trend") or "-")]))

    if by.get("เฝ้าดู"):
        L.append("## เฝ้าดู")
        L.append("")
        L.append(", ".join("%s (%.0f)" % (r["ticker"], r["score"]) for r in by["เฝ้าดู"]))
        L.append("")

    news_rows = [r for r in rows if r.get("news_neg_severity", 0) >= meta["min_severity"]]
    if news_rows:
        L.append("## ข่าวลบที่ควรรู้")
        L.append("")
        for r in news_rows:
            for it in r["news_items"]:
                if (it.get("sentiment") or 0) < 0 and (it.get("severity") or 0) >= meta["min_severity"]:
                    L.append("- **%s** (ระดับ %s) [%s](%s) %s" % (
                        r["ticker"], it.get("severity"), it["title"], it["link"], it.get("summary_th") or ""))
        L.append("")

    fails = Counter(reason for r in by.get("ไม่ผ่านเกณฑ์", []) for reason in r["reasons"])
    if fails:
        L.append("## ไม่ผ่านด่านคัดออก %d ตัว" % len(by["ไม่ผ่านเกณฑ์"]))
        L.append("")
        L.append("สาเหตุหลัก: " + ", ".join("%s (%d)" % (k.split(" (")[0], v) for k, v in fails.most_common(6)))
        L.append("")

    L.append("---")
    L.append("ค่าที่ใช้: น้ำหนัก %s · ผลตอบแทนที่ต้องการ %.1f%% · ส่วนเผื่อความปลอดภัย %d%%" % (
        meta["weights"], meta["required_return"], meta["mos"]))
    L.append("")
    L.append("*รายงานนี้คำนวณอัตโนมัติจากข้อมูลสาธารณะ ใช้ประกอบการตัดสินใจ ไม่ใช่คำแนะนำการลงทุน ตรวจสอบงบการเงินและข่าวจากแหล่งทางการก่อนตัดสินใจทุกครั้ง*")
    return "\n".join(L) + "\n"
