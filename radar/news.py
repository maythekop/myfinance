# -*- coding: utf-8 -*-
"""ข่าว: ดึงจาก Google News RSS → ให้ Gemini ประเมิน (ถ้ามีคีย์) หรือใช้คำสำคัญแทน

ผลต่อหุ้นแต่ละตัว: ข่าวลบรุนแรงสุด (severity 1-5) และรายการหัวข่าว
ข่าวไม่ไปเปลี่ยนคะแนนพื้นฐาน ใช้เพื่อระงับ/เตือนจังหวะซื้อขายเท่านั้น
"""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (thai-stock-radar)"}

MACRO_QUERIES = {
    "oil": ("ราคาน้ำมัน", "oil prices OPEC", "en"),
    "usdthb": ("ค่าเงินบาท", "Thai baht dollar", "th"),
    "us10y": ("บอนด์ยีลด์สหรัฐ", "US Treasury yields", "en"),
    "gold": ("ราคาทอง", "gold price", "en"),
    "fed": ("เฟด ดอกเบี้ย", "Federal Reserve interest rates", "en"),
    "china": ("เศรษฐกิจจีน", "China economy", "en"),
    "tariff": ("ภาษีศุลกากร สหรัฐ", "US tariffs trade", "en"),
    "thai_politics": ("การเมืองไทย เศรษฐกิจ", "Thailand politics economy", "th"),
}

NEG_WORDS = [
    "ขาดทุน", "กำไรลด", "กำไรร่วง", "ลดปันผล", "งดจ่ายปันผล", "ฟ้อง", "ทุจริต", "สอบสวน", "ก.ล.ต. กล่าวโทษ",
    "ผิดนัดชำระ", "ปรับลดเป้า", "ร่วงหนัก", "ดิ่ง", "ไฟไหม้", "ระงับการซื้อขาย", "ขึ้นเครื่องหมาย SP",
    "loss", "plunge", "fraud", "probe", "lawsuit", "default", "downgrade", "dividend cut", "suspend",
]
SEVERE_WORDS = ["ทุจริต", "ผิดนัดชำระ", "งดจ่ายปันผล", "ระงับการซื้อขาย", "fraud", "default", "suspend", "กล่าวโทษ"]
POS_WORDS = ["กำไรเพิ่ม", "กำไรโต", "ทำสถิติ", "เพิ่มปันผล", "ปรับเพิ่มเป้า", "upgrade", "record profit", "beat"]


def google_news(query, lang="th", days=3, limit=5):
    q = urllib.parse.quote("%s when:%dd" % (query, max(1, days)))
    gl, ceid = ("TH", "TH:th") if lang == "th" else ("US", "US:en")
    url = "https://news.google.com/rss/search?q=%s&hl=%s&gl=%s&ceid=%s" % (q, lang, gl, ceid)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        pub = it.findtext("pubDate") or ""
        try:
            pub_iso = parsedate_to_datetime(pub).isoformat()
        except Exception:
            pub_iso = pub
        items.append({"title": title, "link": it.findtext("link") or "",
                      "source": src.text if src is not None else "", "published": pub_iso})
        if len(items) >= limit:
            break
    return items


def gather(candidates, cfg, fetch=google_news):
    """candidates: list ของ dict ที่มี ticker, name; คืนรายการข่าวพร้อม about"""
    n = cfg["timing_news"]
    days = max(1, int(round(n["lookback_hours"] / 24.0)))
    per_t = n.get("news_per_ticker", 3)
    out, seen = [], set()

    def add(items, about, kind):
        for it in items:
            key = it["title"][:80]
            if key in seen:
                continue
            seen.add(key)
            it.update({"about": about, "kind": kind})
            out.append(it)

    for c in candidates:
        try:
            add(fetch("หุ้น %s" % c["ticker"], "th", days, per_t), c["ticker"], "stock")
        except Exception:
            pass
    for topic in n.get("macro_watch", []):
        q = MACRO_QUERIES.get(topic)
        if not q:
            continue
        th, en, lang = q
        try:
            add(fetch(th if lang == "th" else en, lang, days, n.get("news_per_macro", 2)), topic, "macro")
        except Exception:
            pass
    return out[: cfg["ai"].get("max_news_per_run", 60)]


# ---------------------------------------------------------------- วิเคราะห์ข่าว

def keyword_assess(items):
    for it in items:
        t = it["title"].lower()
        neg = any(w.lower() in t for w in NEG_WORDS)
        severe = any(w.lower() in t for w in SEVERE_WORDS)
        pos = any(w.lower() in t for w in POS_WORDS)
        if severe:
            it.update(sentiment=-1, severity=4)
        elif neg:
            it.update(sentiment=-1, severity=3)
        elif pos:
            it.update(sentiment=1, severity=2)
        else:
            it.update(sentiment=0, severity=1)
        it.update(sectors=[], summary_th="", assessed_by="keyword")
    return items


GEMINI_PROMPT = """คุณเป็นนักวิเคราะห์หุ้นไทยสายคุณค่า/ปันผล ประเมินหัวข่าวต่อไปนี้
กลุ่มอุตสาหกรรมที่ใช้ได้: {sectors}

สำหรับแต่ละข่าว ให้ประเมิน:
- sentiment: -1 (ลบต่อผู้ถือหุ้น), 0 (กลาง), 1 (บวก)
- severity: 1-5 (1 = แทบไม่มีผล, 3 = มีผลต่อกำไร/ปันผลปีนี้, 5 = กระทบความอยู่รอดหรือความน่าเชื่อถือของกิจการ)
- sectors: เฉพาะข่าวมหภาค ระบุกลุ่มที่ได้รับผลกระทบ [{{"sector": "...", "direction": -1 หรือ 1}}] ใช้ชื่อกลุ่มจากรายการข้างต้นเท่านั้น
- summary_th: สรุปผลกระทบสั้น ๆ ภาษาไทย ไม่เกิน 1 ประโยค อ้างอิงเฉพาะสิ่งที่อยู่ในหัวข่าว ห้ามเดา

ตอบเป็น JSON array เท่านั้น: [{{"i": เลขข่าว, "sentiment": ..., "severity": ..., "sectors": [...], "summary_th": "..."}}]

ข่าว:
{items}
"""


def gemini_assess(items, sectors, api_key, model):
    lines = []
    for i, it in enumerate(items):
        about = ("หุ้น " + it["about"]) if it["kind"] == "stock" else ("มหภาค: " + it["about"])
        lines.append("%d. [%s] %s" % (i, about, it["title"]))
    prompt = GEMINI_PROMPT.format(sectors=", ".join(sorted(sectors)), items="\n".join(lines))
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }).encode("utf-8")
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    text = re.sub(r"^```(json)?|```$", "", text.strip()).strip()
    results = {int(r["i"]): r for r in json.loads(text) if "i" in r}
    for i, it in enumerate(items):
        r = results.get(i)
        if r is None:
            keyword_assess([it])
            continue
        it.update(sentiment=int(r.get("sentiment", 0)), severity=int(r.get("severity", 1)),
                  sectors=r.get("sectors") or [], summary_th=r.get("summary_th", ""), assessed_by="gemini")
    return items


def assess(items, sectors, cfg, api_key):
    if not items:
        return items, "ไม่มีข่าว"
    if api_key:
        try:
            return gemini_assess(items, sectors, api_key, cfg["ai"]["model"]), "Gemini"
        except Exception as e:  # noqa: BLE001
            return keyword_assess(items), "คำสำคัญ (Gemini ล้มเหลว: %s)" % str(e)[:120]
    return keyword_assess(items), "คำสำคัญ (ยังไม่ได้ใส่ GEMINI_API_KEY)"


def attach_to_rows(rows, items, cfg):
    """สรุปข่าวรายหุ้น: news_neg_severity, news_items, macro_flags"""
    n = cfg["timing_news"]
    by_t = {r["ticker"]: r for r in rows}
    for r in rows:
        r["news_neg_severity"] = 0
        r["news_items"] = []
        r["macro_flags"] = []
    for it in items:
        if it["kind"] == "stock" and it["about"] in by_t:
            r = by_t[it["about"]]
            r["news_items"].append({k: it.get(k) for k in ("title", "link", "source", "published", "sentiment", "severity", "summary_th")})
            if it.get("sentiment", 0) < 0:
                r["news_neg_severity"] = max(r["news_neg_severity"], it.get("severity", 0))
        elif it["kind"] == "macro" and it.get("severity", 0) >= n["min_severity_to_flag"]:
            for s in it.get("sectors") or []:
                for r in rows:
                    if r["sector"] == s.get("sector"):
                        r["macro_flags"].append({"topic": it["about"], "direction": s.get("direction"),
                                                 "severity": it.get("severity"), "title": it["title"],
                                                 "summary_th": it.get("summary_th", "")})
    return rows
