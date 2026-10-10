# -*- coding: utf-8 -*-
import math
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    BKK = ZoneInfo("Asia/Bangkok")
except Exception:  # pragma: no cover
    BKK = None


def now_bkk():
    return datetime.now(BKK) if BKK else datetime.now()


def num(v):
    """แปลงเป็น float; ค่าว่าง/NaN/ข้อความ คืน None"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def std(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def rnd(v, d=2):
    return None if v is None else round(v, d)
