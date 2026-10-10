# -*- coding: utf-8 -*-
"""ตัดสินสัญญาณ: พื้นฐาน (คะแนน) + ราคาเหมาะสม (โซนซื้อ) + จังหวะ (เทคนิค) + ข่าว

ลำดับความสำคัญ
  1. ไม่ผ่านด่านคัดออก        → ไม่ผ่านเกณฑ์
  2. มีเหตุให้ทบทวนการขาย     → ทบทวนขาย
  3. คะแนน ≥ เกณฑ์ Buy List:
       ราคา ≤ โซนซื้อ + ไม่มีข่าวลบรุนแรง → ซื้อ
         (ถ้าตั้ง buy_confirm_mode = chandelier ต้องรอ Chandelier รายวันกลับเป็นขาขึ้นก่อน มิฉะนั้น → รอราคา)
       ราคา ≤ โซนซื้อ แต่มีข่าวลบรุนแรง   → รอข่าวคลี่คลาย
       ราคายังสูงกว่าโซนซื้อ               → รอราคา
  4. คะแนน ≥ เกณฑ์ Watch List → เฝ้าดู
  5. อื่น ๆ                   → คะแนนต่ำ
"""

ORDER = ["ซื้อ", "ทบทวนขาย", "รอข่าวคลี่คลาย", "รอราคา", "เฝ้าดู", "คะแนนต่ำ", "ไม่ผ่านเกณฑ์"]


def decide(r, cfg, prev_score=None):
    sc, ts, tt, tn = cfg["scoring"], cfg["timing_signal"], cfg["timing_technical"], cfg["timing_news"]
    reasons, notes = [], []
    price = r.get("price")

    if not r.get("passed_filters"):
        return "ไม่ผ่านเกณฑ์", list(r.get("filter_fails") or []), notes

    score = r.get("score")
    neg_sev = r.get("news_neg_severity", 0) or 0
    severe_news = neg_sev >= max(4, tn["min_severity_to_flag"])
    neg_news = neg_sev >= tn["min_severity_to_flag"]

    # ---------- ทบทวนการขาย ----------
    sell = []
    if r.get("trim_price") and price and price >= r["trim_price"]:
        sell.append("ราคาสูงกว่ามูลค่ายุติธรรมเกิน %d%%" % cfg["fair_value"]["premium_trim_pct"])
    if r.get("dividend_cut"):
        sell.append("ปันผลปีล่าสุดลดลงเกิน %d%%" % ts.get("dividend_cut_pct", 20))
    if severe_news:
        sell.append("มีข่าวลบรุนแรง (ระดับ %d)" % neg_sev)
    if prev_score is not None and score is not None and prev_score - score >= ts["score_drop_points"]:
        sell.append("คะแนนลดลง %.0f แต้มจากรอบก่อน" % (prev_score - score))
    if sell and score is not None and score >= sc["watch_list_min_score"]:
        return "ทบทวนขาย", sell, notes

    # ---------- หมายเหตุจังหวะ ----------
    rsi = r.get("rsi")
    if rsi is not None and rsi <= tt["rsi_oversold"]:
        notes.append("RSI %.0f ขายมากเกินไป" % rsi)
    if rsi is not None and rsi >= tt["rsi_overbought"]:
        notes.append("RSI %.0f ซื้อมากเกินไป" % rsi)
    if r.get("from_low_pct") is not None and r["from_low_pct"] <= tt["near_52w_low_pct"]:
        notes.append("ใกล้จุดต่ำสุดรอบปี (+%.1f%%)" % r["from_low_pct"])
    if r.get("trend") == "ขาลง":
        notes.append("แนวโน้มราคายังเป็นขาลง ควรทยอยซื้อ")
    ce_dir, ce_turn = r.get("ce_dir"), r.get("ce_short_stop")
    if ce_dir == 1 and r.get("ce_flip_bars") is not None and r["ce_flip_bars"] <= tt.get("chandelier_fresh_days", 5):
        notes.append("Chandelier เพิ่งกลับเป็นขาขึ้น (%d วันทำการก่อน)" % r["ce_flip_bars"] if r["ce_flip_bars"] else "Chandelier กลับเป็นขาขึ้นวันนี้")
    if r.get("cew_dir") == -1 and r.get("cew_flip_bars") is not None and r["cew_flip_bars"] <= 2:
        notes.append("แนวโน้มรายสัปดาห์เพิ่งหลุดเส้น Chandelier (ผู้ถือควรทบทวน)")
    for f in r.get("macro_flags") or []:
        if f.get("direction") == -1:
            notes.append("มหภาคกดดันกลุ่ม: %s" % (f.get("summary_th") or f.get("title")))
    if neg_news and not severe_news:
        notes.append("มีข่าวลบระดับ %d" % neg_sev)

    if score is None:
        return "คะแนนต่ำ", ["ข้อมูลไม่พอให้คะแนน"], notes

    if score >= sc["buy_list_min_score"]:
        bp = r.get("buy_price")
        if bp and price and price <= bp:
            confirm = ts.get("buy_confirm_mode", "none")
            if confirm == "price_above_sma_short" and r.get("sma_short") and price < r["sma_short"]:
                return "รอราคา", ["อยู่ในโซนซื้อแล้ว รอราคายืนเหนือเส้น %d วัน" % tt["sma_short_days"]], notes
            if confirm == "chandelier" and ce_dir == -1:
                return "รอราคา", ["อยู่ในโซนซื้อแล้ว รอแนวโน้มกลับตัว: ราคาปิดเหนือ %.2f (Chandelier)" % ce_turn if ce_turn else "อยู่ในโซนซื้อแล้ว รอแนวโน้มกลับตัว (Chandelier)"], notes
            if confirm != "chandelier" and ce_dir == -1 and ce_turn:
                notes[:] = [x for x in notes if not x.startswith("แนวโน้มราคายังเป็นขาลง")]
                notes.append("แนวโน้มยังเป็นขาลง (Chandelier) ทยอยซื้อ หรือรอซื้อเมื่อปิดเหนือ %.2f" % ce_turn)
            if neg_news and tn.get("negative_news_blocks_buy", True):
                return "รอข่าวคลี่คลาย", ["อยู่ในโซนซื้อ แต่มีข่าวลบระดับ %d" % neg_sev], notes
            reasons.append("คะแนน %.0f และราคาต่ำกว่ามูลค่ายุติธรรม %.0f%%" % (score, -((price / r["fair_value"]) - 1) * 100))
            return "ซื้อ", reasons, notes
        if bp:
            reasons.append("หุ้นผ่านเกณฑ์ รอราคา ≤ %.2f (ห่าง %.1f%%)" % (bp, (price / bp - 1) * 100))
        else:
            reasons.append("หุ้นผ่านเกณฑ์ แต่คำนวณมูลค่ายุติธรรมไม่ได้")
        return "รอราคา", reasons, notes

    if score >= sc["watch_list_min_score"]:
        return "เฝ้าดู", ["คะแนน %.0f" % score], notes
    return "คะแนนต่ำ", ["คะแนน %.0f" % score], notes
