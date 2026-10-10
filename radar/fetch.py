# -*- coding: utf-8 -*-
"""ดึงข้อมูลจาก Yahoo Finance (yfinance) แล้วแปลงเป็น dict ธรรมดา (ทดสอบ/บันทึกได้ง่าย)"""
import time

from .util import num

INFO_KEYS = [
    "currentPrice", "regularMarketPrice", "marketCap", "sector", "industry",
    "shortName", "longName", "averageVolume", "trailingPE", "priceToBook",
    "trailingEps", "bookValue", "dividendYield", "trailingAnnualDividendYield",
    "payoutRatio", "returnOnEquity", "profitMargins", "debtToEquity",
    "currentRatio", "freeCashflow",
]

# ตัวแปรมหภาคที่แสดงในรายงาน (ชื่อ: สัญลักษณ์ Yahoo)
MACRO_SYMBOLS = {
    "ดัชนี SET": "^SET.BK",
    "น้ำมันดิบ WTI (USD)": "CL=F",
    "ทองคำ (USD/oz)": "GC=F",
    "USD/THB": "THB=X",
    "บอนด์สหรัฐ 10 ปี (%)": "^TNX",
    "S&P 500": "^GSPC",
}


def _series_to_pairs(series):
    out = []
    for d, v in series.items():
        f = num(v)
        if f is not None:
            out.append([d.strftime("%Y-%m-%d"), f])
    return out


def fetch_raw(ticker, years=6):
    """ข้อมูลครบชุดสำหรับรอบวิเคราะห์เต็ม"""
    import yfinance as yf
    t = yf.Ticker(ticker + ".BK")
    info = t.info or {}
    raw = {"ticker": ticker, "info": {k: info.get(k) for k in INFO_KEYS},
           "dividends": [], "net_income": [], "close": [], "ohlc": []}
    try:
        raw["dividends"] = _series_to_pairs(t.dividends)
    except Exception:
        pass
    try:
        inc = t.income_stmt
        if inc is not None and not inc.empty and "Net Income" in inc.index:
            raw["net_income"] = [num(v) for v in inc.loc["Net Income"].tolist()]  # ใหม่ → เก่า
    except Exception:
        pass
    try:
        h = t.history(period="%dy" % years, auto_adjust=False)
        raw["close"] = _series_to_pairs(h["Close"])
        raw["ohlc"] = _ohlc(h)
    except Exception:
        pass
    return raw


def _ohlc(h):
    """แท่งราคา [วันที่, สูง, ต่ำ, ปิด] สำหรับ ATR / Chandelier Exit"""
    out = []
    for d, hi, lo, c in zip(h.index, h["High"], h["Low"], h["Close"]):
        hi, lo, c = num(hi), num(lo), num(c)
        if c is not None:
            out.append([d.strftime("%Y-%m-%d"), hi if hi is not None else c, lo if lo is not None else c, c])
    return out


def fetch_ohlc(ticker, period="2y"):
    """แท่งราคาย้อนหลัง (รอบข่าว) — 2 ปีพอสำหรับเส้นค่าเฉลี่ย 200 วันและ Chandelier รายสัปดาห์"""
    import yfinance as yf
    return _ohlc(yf.Ticker(ticker + ".BK").history(period=period, auto_adjust=False))


def fetch_close(ticker, period="1y"):
    """ราคาปิดย้อนหลัง (ใช้ในรอบข่าวเพื่ออัปเดตราคาและสัญญาณเทคนิค)"""
    import yfinance as yf
    h = yf.Ticker(ticker + ".BK").history(period=period, auto_adjust=False)
    return _series_to_pairs(h["Close"])


def fetch_macro():
    import yfinance as yf
    out = []
    for name, sym in MACRO_SYMBOLS.items():
        try:
            h = yf.Ticker(sym).history(period="10d")
            closes = [num(v) for v in h["Close"].tolist() if num(v) is not None]
            if len(closes) >= 2:
                out.append({"name": name, "symbol": sym, "last": closes[-1],
                            "chg_pct": (closes[-1] / closes[-2] - 1) * 100,
                            "chg_5d_pct": (closes[-1] / closes[max(0, len(closes) - 6)] - 1) * 100})
        except Exception:
            pass
        time.sleep(0.5)
    return out


def with_retry(fn, *args, retries=2, wait=3):
    last = None
    for i in range(retries + 1):
        try:
            return fn(*args), None
        except Exception as e:  # noqa: BLE001
            last = str(e)[:200]
            time.sleep(wait * (i + 1))
    return None, last
