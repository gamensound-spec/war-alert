"""환율·코스피 시장 스트레스 참고 지표. 주의까지만 판단하며 경보는 만들지 않는다."""
import datetime as dt
import json
import math
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from news_monitor import robust_z

SYMBOLS = {"KRW=X": "원/달러 환율", "^KS11": "코스피"}
SERIES_DAYS, CHANGE_DAYS, BASE_DAYS, MIN_BASE = 90, 20, 60, 30
Z_WATCH = 2.0
JSON_FILE = "data/market.json"
KST = dt.timezone(dt.timedelta(hours=9))
NOTICE = "대리 지표 · 신뢰도 낮음 · 경보 없음"


def number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def parse_chart(payload):
    """null 종가는 같은 위치의 날짜와 함께 제외한다. 잘못된 응답은 종목 실패로 처리."""
    try:
        chart = payload["chart"]
        if chart.get("error"):
            raise ValueError("Yahoo chart API 오류")
        result = chart["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        if not isinstance(timestamps, list) or not isinstance(closes, list) or len(timestamps) != len(closes):
            raise ValueError("Yahoo 날짜·종가 배열 불일치")
        meta = result.get("meta") or {}
        try:
            tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            tz = dt.timezone.utc
        days = {}
        for timestamp, close in zip(timestamps, closes):
            if not number(timestamp) or not number(close) or close <= 0:
                continue
            try:
                date = dt.datetime.fromtimestamp(timestamp, tz).date().isoformat()
            except (ValueError, OverflowError, OSError):
                continue
            days[date] = {"date": date, "close": close}
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError("Yahoo chart 응답 형식 오류") from exc
    if not days:
        raise ValueError("Yahoo 유효한 일별 종가 없음")
    return [days[date] for date in sorted(days)][-SERIES_DAYS:]


def fetch(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="")
    for attempt, wait in enumerate((0, 15, 30)):
        if wait:
            time.sleep(wait)
        response = requests.get(url, params={"range": "6mo", "interval": "1d"},
                                headers={"User-Agent": "Mozilla/5.0 (compatible; market-monitor/1.0)"},
                                timeout=30)
        if response.status_code == 429:
            if attempt == 2:
                raise RuntimeError("Yahoo 요청 제한(429): 15·30초 재시도 후 포기")
            continue
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            if attempt == 2:
                raise RuntimeError("Yahoo 비 JSON 응답: 15·30초 재시도 후 포기") from exc
            continue
        return parse_chart(payload)


def evaluate(symbol, days):
    closes = [day["close"] for day in days]
    returns = [(b / a - 1) * 100 for a, b in zip(closes, closes[1:])]
    # 최근 20일 구간은 기준선에 포함하지 않는다. 단위는 모두 %.
    base = returns[:-CHANGE_DAYS][-BASE_DAYS:]
    change = (closes[-1] / closes[-CHANGE_DAYS - 1] - 1) * 100 if len(returns) >= CHANGE_DAYS else None
    median, z = None, None
    if len(base) >= MIN_BASE and change is not None:
        # 20일 누적 변화는 일간 변화율 분포와 비교하기 전에 √20으로 나눠 단위를 맞춘다
        median, z = robust_z(change / math.sqrt(CHANGE_DAYS), base)
        if z is not None:
            z *= -1 if symbol == "^KS11" else 1
            if not math.isfinite(z):
                z = None
    return {"date": days[-1]["date"], "close": closes[-1],
            "change_pct": returns[-1] if returns else None,
            "change_20d_pct": change, "base_n": len(base),
            "median": median, "z": z,
            "status": "muted" if z is None else "watch" if z >= Z_WATCH else "normal"}


def classify(latest):
    stressed = [symbol for symbol, item in latest.items()
                if item.get("z") is not None and item["z"] >= Z_WATCH]
    watch = [f"{SYMBOLS[symbol]} 스트레스 증가 (z {latest[symbol]['z']:+.2f})" for symbol in stressed]
    if len(stressed) == len(SYMBOLS):
        watch.append("환율·코스피 동시 악화")
    status = "watch" if stressed else "normal" if all(item.get("z") is not None for item in latest.values()) else "muted"
    return status, watch


def write_json(out):
    """완성된 JSON만 교체한다. 수집/직렬화/쓰기 실패 시 직전 파일을 유지한다."""
    path = Path(JSON_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".market-", suffix=".tmp", delete=False) as f:
            temporary = f.name
            json.dump(out, f, ensure_ascii=False, indent=1, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def run(fetcher=fetch):
    latest, series, errors, lines = {}, {}, {}, []
    for symbol, label in SYMBOLS.items():
        try:
            days = fetcher(symbol)
            item = evaluate(symbol, days)
        except (requests.RequestException, RuntimeError, ValueError, KeyError, IndexError, TypeError) as exc:
            errors[symbol] = str(exc)
            latest[symbol] = {"error": str(exc), "status": "muted"}
            series[symbol] = []
            lines.append(f"{label}: 수집 실패 · {exc}")
            continue
        latest[symbol], series[symbol] = item, days
        daily = f"{item['change_pct']:+.2f}%" if item["change_pct"] is not None else "—"
        score = f"z {item['z']:+.2f}" if item["z"] is not None else f"판단 보류(기준선 {item['base_n']}/{MIN_BASE}일 또는 MAD 0)"
        lines.append(f"{label} {item['date']}: 종가 {item['close']:,.2f} · 전일 대비 {daily} · {score}")
    if len(errors) == len(SYMBOLS):
        raise RuntimeError("시장 데이터 모두 수집 실패: " + "; ".join(f"{s}: {e}" for s, e in errors.items()))
    status, watch = classify(latest)
    out = {"generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
           "source": "yahoo-chart-unofficial",
           "config": {"series_days": SERIES_DAYS, "change_days": CHANGE_DAYS,
                      "base_days": BASE_DAYS, "min_base": MIN_BASE, "z_watch": Z_WATCH,
                      "method": "20d cumulative return (%) / sqrt(20) vs preceding 60 daily returns; median/MAD * 1.4826; KOSPI sign inverted"},
           "status": status, "alerts": [], "watch": watch, "latest": latest, "series": series}
    if errors:
        out["error"] = errors
    write_json(out)
    lines += [f"주의: {item}" for item in watch]
    lines += [f"판정: {status}", f"출처: Yahoo Finance (비공식 API) · {NOTICE}"]
    return [], lines


if __name__ == "__main__":
    alerts, lines = run()
    print(*lines, sep="\n")
