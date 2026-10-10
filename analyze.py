# -*- coding: utf-8 -*-
"""
Thai Stock Radar: วิเคราะห์หุ้นคุณค่า/ปันผล

  python analyze.py --mode full   รอบเต็ม (วันละครั้งหลังตลาดปิด)
                                  พื้นฐาน → คะแนน → มูลค่ายุติธรรม → จังหวะเทคนิค → ข่าว → สัญญาณ
  python analyze.py --mode news   รอบเร็ว (ทุก 3 ชม.) ใช้คะแนนจากรอบเต็มล่าสุด
                                  อัปเดตราคา/เทคนิคของหุ้นที่น่าสนใจ + ข่าวใหม่ → สัญญาณใหม่

ตัวเลือก: --limit N (ทดสอบเร็ว), --out output, --history history
คีย์ Gemini อ่านจาก environment GEMINI_API_KEY (ไม่ใส่ก็ได้ ระบบจะใช้คำสำคัญแทน)
"""
import argparse
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from radar import fetch as F  # noqa: E402
from radar import fundamentals, news, report, scoring, signals, technical, valuation  # noqa: E402
from radar.util import now_bkk, rnd  # noqa: E402


def load_cfg(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    pw = cfg["pillar_weights"]
    if sum(pw.values()) <= 0:
        raise SystemExit("pillar_weights รวมต้องมากกว่า 0")
    return cfg


def load_universe(path, cfg):
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("ticker", "").strip()]
    if cfg["universe"].get("index", "SET100").upper() == "SET50":
        rows = [r for r in rows if str(r.get("in_set50", "")).strip() == "1"]
    return [r["ticker"].strip().upper() for r in rows]


def apply_price_layers(r, close, cfg, ohlc=None):
    """ราคา + เทคนิค + เส้นแนวโน้ม Chandelier + มูลค่ายุติธรรม (เรียกได้ทั้งรอบเต็มและรอบข่าว)"""
    t = technical.compute(close, cfg)
    r.update(technical.compute_trend_stops(ohlc or technical.bars_from_close(close), cfg))
    r.update(rsi=t["rsi"], sma_short=t["sma_short"], sma_long=t["sma_long"], high_52w=t["high_52w"],
             low_52w=t["low_52w"], from_low_pct=t["from_low_pct"], from_high_pct=t["from_high_pct"],
             trend=t["trend"], price_date=t["price_date"])
    if t["last_close"]:
        r["price"] = t["last_close"]
        if r.get("ttm_div"):
            r["div_yield_pct"] = r["ttm_div"] / r["price"] * 100
    r.update(valuation.fair_value(r, cfg))
    return r


def news_candidates(rows, cfg):
    wmin = cfg["scoring"]["watch_list_min_score"]
    c = [r for r in rows if r.get("passed_filters") and (r.get("score") or 0) >= wmin]
    c.sort(key=lambda r: (0 if (r.get("buy_price") and r.get("price") and r["price"] <= r["buy_price"] * 1.05) else 1,
                          -(r.get("score") or 0)))
    return c[: cfg["timing_news"].get("max_tickers_for_news", 30)]


def run_news_and_signals(rows, cfg, news_fetch, api_key):
    cands = news_candidates(rows, cfg)
    items = news.gather([{"ticker": r["ticker"], "name": r["name"]} for r in cands], cfg, fetch=news_fetch)
    sectors = {r["sector"] for r in rows if r.get("sector")}
    items, method = news.assess(items, sectors, cfg, api_key)
    news.attach_to_rows(rows, items, cfg)
    for r in rows:
        sig, reasons, notes = signals.decide(r, cfg, r.get("prev_score"))
        r.update(signal=sig, reasons=reasons, notes=notes)
    return method, len(items)


def clean(r):
    out = {}
    for k, v in r.items():
        out[k] = rnd(v, 4) if isinstance(v, float) else v
    return out


def meta_for(cfg, mode, method, macro):
    return {"mode": mode, "generated_at": now_bkk().strftime("%Y-%m-%d %H:%M"), "news_method": method,
            "macro": macro, "min_severity": cfg["timing_news"]["min_severity_to_flag"],
            "weights": ", ".join("%s %s" % (scoring.PILLAR_TH[k], v) for k, v in cfg["pillar_weights"].items()),
            "required_return": cfg["fair_value"]["required_return_pct"],
            "mos": cfg["fair_value"]["margin_of_safety_buy_pct"]}


def save_history(rows, meta, hist_dir, mode):
    os.makedirs(os.path.join(hist_dir, "scores"), exist_ok=True)
    with open(os.path.join(hist_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "stocks": rows}, f, ensure_ascii=False, indent=1, default=str)
    if mode == "full":
        day = now_bkk().strftime("%Y-%m-%d")
        with open(os.path.join(hist_dir, "scores", day + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "ticker", "signal", "score", "price", "fair_value", "buy_price", "div_yield_pct"])
            for r in rows:
                w.writerow([day, r["ticker"], r["signal"], r.get("score"), rnd(r.get("price")),
                            rnd(r.get("fair_value")), rnd(r.get("buy_price")), rnd(r.get("div_yield_pct"))])


def load_latest(hist_dir):
    p = os.path.join(hist_dir, "latest.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def mode_full(cfg, tickers, args, fetch_raw, fetch_macro, news_fetch, api_key, delay):
    prev = load_latest(args.history)
    prev_scores = {s["ticker"]: s.get("score") for s in (prev or {}).get("stocks", [])}
    today = now_bkk()
    rows, failed = [], []
    for i, tk in enumerate(tickers, 1):
        raw, err = F.with_retry(fetch_raw, tk)
        if not raw or (not raw.get("close") and not (raw.get("info") or {}).get("marketCap")):
            failed.append(tk)
            print("[%d/%d] %s ล้มเหลว %s" % (i, len(tickers), tk, err or ""), flush=True)
        else:
            m = fundamentals.compute_metrics(raw, cfg, today)
            apply_price_layers(m, raw.get("close") or [], cfg, raw.get("ohlc"))
            m["prev_score"] = prev_scores.get(tk)
            rows.append(m)
            print("[%d/%d] %s ok" % (i, len(tickers), tk), flush=True)
        time.sleep(delay)
    if not rows:
        raise SystemExit("ดึงข้อมูลไม่ได้เลย ตรวจการเชื่อมต่อหรือรายชื่อหุ้น")
    scoring.score_all(rows, cfg)
    macro = fetch_macro()
    method, n_items = run_news_and_signals(rows, cfg, news_fetch, api_key)
    meta = meta_for(cfg, "full", method, macro)
    meta.update(failed=failed, news_count=n_items)
    rows = report.write_all([clean(r) for r in rows], args.out, meta)
    save_history(rows, meta, args.history, "full")
    return rows, meta


def mode_news(cfg, args, fetch_ohlc, fetch_macro, news_fetch, api_key, delay):
    latest = load_latest(args.history)
    if not latest:
        print("ยังไม่มีผลรอบเต็ม ข้ามรอบนี้ (ให้รัน 'วิเคราะห์รอบเต็ม' ก่อน 1 ครั้ง)")
        sys.exit(0)
    rows = latest["stocks"]
    for r in news_candidates(rows, cfg):
        ohlc, err = F.with_retry(fetch_ohlc, r["ticker"])
        if ohlc:
            apply_price_layers(r, [[b[0], b[3]] for b in ohlc], cfg, ohlc)
        time.sleep(delay)
    macro = fetch_macro()
    method, n_items = run_news_and_signals(rows, cfg, news_fetch, api_key)
    meta = meta_for(cfg, "news", method, macro)
    meta.update(news_count=n_items, fundamentals_from=latest["meta"].get("generated_at"))
    rows = report.write_all([clean(r) for r in rows], args.out, meta)
    save_history(rows, meta, args.history, "news")
    return rows, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "news"], default="full")
    ap.add_argument("--config", default=os.path.join(HERE, "config", "settings.json"))
    ap.add_argument("--universe", default=os.path.join(HERE, "universe", "set100.csv"))
    ap.add_argument("--out", default="output")
    ap.add_argument("--history", default=os.path.join(HERE, "history"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    cfg = load_cfg(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if args.mode == "full":
        tickers = load_universe(args.universe, cfg)
        if args.limit:
            tickers = tickers[: args.limit]
        rows, meta = mode_full(cfg, tickers, args, F.fetch_raw, F.fetch_macro, news.google_news, api_key, args.delay)
    else:
        rows, meta = mode_news(cfg, args, F.fetch_ohlc, F.fetch_macro, news.google_news, api_key, args.delay)
    c = {}
    for r in rows:
        c[r["signal"]] = c.get(r["signal"], 0) + 1
    print("\nเสร็จ: " + ", ".join("%s %d" % (k, v) for k, v in c.items()) + "  ดูรายงานที่ %s/report.md" % args.out)


if __name__ == "__main__":
    main()
