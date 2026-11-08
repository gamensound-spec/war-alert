"""대중 관심도 참고 지표. 출처별 실패를 분리하고 경보는 만들지 않는다."""
import csv
import datetime as dt
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import requests

from news_monitor import robust_z

ARTICLES = ("North_Korea", "Korean_War", "Korean_Demilitarized_Zone", "Kim_Jong_Un")
WIKI_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
TRENDS_API = "https://trends.google.com/trending/rss?geo=KR"
KEYWORDS = ("전쟁", "북한", "미사일", "핵", "대피", "비상식량", "징집", "참전")
SERIES_DAYS, BASE_DAYS, MIN_BASE, Z_WATCH = 60, 28, 14, 2.0
JSON_FILE, CSV_FILE = "data/attention.json", "data/attention_trends.csv"
KST = dt.timezone(dt.timedelta(hours=9))
NOTICE = "참고 지표 · 신뢰도 낮음 · 경보 없음"


def count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def atomic_write(path, writer):
    """직렬화·교체 실패 시 이전 파일과 바이트를 그대로 보존한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".attention-", suffix=".tmp", delete=False) as f:
            temporary = f.name
            writer(f)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def write_json(out):
    atomic_write(JSON_FILE, lambda f: json.dump(out, f, ensure_ascii=False, indent=1, allow_nan=False))


def read_log(path, fields):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["date", *fields]:
            raise ValueError("스냅샷 CSV 열 불일치")
        days = {}
        for row in reader:
            date = dt.date.fromisoformat(row["date"]).isoformat()
            values = {key: int(row[key]) for key in fields}
            if any(value < 0 for value in values.values()):
                raise ValueError("스냅샷 CSV 음수 건수")
            days[date] = {"date": date, **values}
    return [days[date] for date in sorted(days)]


def write_log(path, rows, fields):
    def writer(f):
        output = csv.DictWriter(f, fieldnames=["date", *fields])
        output.writeheader()
        output.writerows(rows)
    atomic_write(path, writer)


def upsert(rows, row):
    days = {item["date"]: item for item in rows}
    days[row["date"]] = row
    return [days[date] for date in sorted(days)]


def baseline(rows, date, field):
    start = (dt.date.fromisoformat(date) - dt.timedelta(days=BASE_DAYS)).isoformat()
    return [row[field] for row in rows if start <= row["date"] < date]


def score(value, base, direction=1):
    median, z = robust_z(value, base) if len(base) >= MIN_BASE else (None, None)
    z = direction * z if z is not None else None
    if z is not None and not math.isfinite(z):
        z = None
    return {"base_n": len(base), "median": median, "z": z,
            "status": "muted" if z is None else "watch" if z >= Z_WATCH else "normal"}


def parse_pageviews(payload, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=SERIES_DAYS)
    try:
        items = payload["items"]
        if not isinstance(items, list):
            raise ValueError("Wikimedia items 배열 없음")
        days = {}
        for item in items:
            if not isinstance(item, dict) or not count(item.get("views")):
                continue
            try:
                date = dt.datetime.strptime(item["timestamp"], "%Y%m%d%H").date()
            except (KeyError, TypeError, ValueError):
                continue
            if start <= date < today:
                days[date.isoformat()] = {"date": date.isoformat(), "views": item["views"]}
    except (KeyError, TypeError) as exc:
        raise ValueError("Wikimedia 응답 형식 오류") from exc
    if not days:
        raise ValueError("Wikimedia 유효한 확정 일별 조회수 없음")
    return [days[date] for date in sorted(days)]


def fetch_wiki(today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    start, end = today - dt.timedelta(days=SERIES_DAYS), today - dt.timedelta(days=1)
    pages = {}
    for title in ARTICLES:
        url = f"{WIKI_API}/{quote(title, safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}"
        response = requests.get(url, headers={"User-Agent": "war-alert/1.0"}, timeout=30)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        pages[title] = parse_pageviews(response.json(), today)
    if not pages:
        raise ValueError("Wikimedia 문서 4개 모두 데이터 없음(404)")
    # 누락을 0으로 간주하지 않고 같은 문서 집합이 존재하는 날짜끼리 비교한다.
    by_title = {title: {row["date"]: row["views"] for row in rows} for title, rows in pages.items()}
    common = set.intersection(*(set(days) for days in by_title.values()))
    if not common:
        raise ValueError("Wikimedia 문서 간 공통 확정일 없음")
    return [{"date": date, "total": sum(days[date] for days in by_title.values()),
             "documents": {title: days[date] for title, days in by_title.items()}}
            for date in sorted(common)][-SERIES_DAYS:]


def evaluate_wiki(days):
    last = days[-1]
    latest = {**last, **score(last["total"], baseline(days, last["date"], "total"))}
    return {"status": latest["status"], "latest": latest, "series": days,
            "missing_articles": [title for title in ARTICLES if title not in last["documents"]]}


def parse_trends(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("Google Trends RSS XML 형식 오류") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Google Trends RSS channel 없음")
    items, hits, titles = root.findall("./channel/item"), 0, []
    for item in items:
        candidates = [item.findtext("title", default="")]
        candidates += [node.text or "" for node in item.iter()
                       if node.tag.rsplit("}", 1)[-1] == "news_item_title"]
        matches = [title.strip() for title in candidates if any(word in title for word in KEYWORDS)]
        # 키워드 개수가 아니라 키워드를 포함한 제목(title·뉴스 제목) 수를 센다.
        hits += len(matches)
        for title in matches:
            if title not in titles:
                titles.append(title)
    return {"hits": hits, "items": len(items), "titles": titles[:5]}


def fetch_trends():
    response = requests.get(TRENDS_API, headers={"User-Agent": "war-alert/1.0"}, timeout=30)
    response.raise_for_status()
    return parse_trends(response.text)


def evaluate_trends(snapshot, rows, date):
    base = baseline(rows, date, "keyword_hits")
    result = {**snapshot, "date": date, "samples": sum(row["date"] <= date for row in rows),
              **score(snapshot["hits"], base)}
    if len(base) >= MIN_BASE and result["z"] is None:
        # MAD 0이면 z를 만들어내지 않고 관측 건수만 보여 준다.
        result["status"] = "watch" if snapshot["hits"] >= 3 else "normal"
        result["note"] = f"평소 {result['median']:g}건 대비 {snapshot['hits']}건 · MAD 0"
    else:
        result["note"] = (f"z {result['z']:+.2f}" if result["z"] is not None
                          else f"판단 보류(기준선 {len(base)}/{MIN_BASE}일)")
    return result


def run(wiki_fetcher=fetch_wiki, trends_fetcher=fetch_trends, today=None):
    today = today or dt.datetime.now(KST).date()
    results, errors, lines = {}, {}, []
    for source, label in (("wiki", "Wikimedia Pageviews"), ("trends", "Google Trends KR RSS")):
        try:
            if source == "wiki":
                result = evaluate_wiki(wiki_fetcher())
                item = result["latest"]
                hint = (f"z {item['z']:+.2f}" if item["z"] is not None
                        else f"판단 보류(기준선 {item['base_n']}/{MIN_BASE}일 또는 MAD 0)")
                line = f"{label} {item['date']}: 합산 일 조회수 {item['total']:,} · {hint}"
            else:
                snapshot = trends_fetcher()
                rows = upsert(read_log(CSV_FILE, ["keyword_hits", "items"]),
                              {"date": today.isoformat(), "keyword_hits": snapshot["hits"], "items": snapshot["items"]})
                result = evaluate_trends(snapshot, rows, today.isoformat())
                write_log(CSV_FILE, rows, ["keyword_hits", "items"])
                line = f"{label} {result['date']}: 인기 검색어 {result['items']}개 · 관련 제목 {result['hits']}건 · {result['note']}"
        except (requests.RequestException, RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
            errors[source] = str(exc)
            result = {"status": "muted", "error": str(exc)}
            line = f"{label}: 수집 실패 · {exc}"
        results[source] = result
        lines.append(line)
    if len(errors) == 2:
        raise RuntimeError("관심도 데이터 모두 수집 실패: " + "; ".join(f"{s}: {e}" for s, e in errors.items()))
    watch = [f"{label} 증가" for source, label in (("wiki", "위키피디아 관심도"), ("trends", "한국 인기 검색어 관심도"))
             if results[source]["status"] == "watch"]
    status = ("watch" if watch else "normal" if all(r["status"] == "normal" for r in results.values()) else "muted")
    out = {"generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
           "source": ["wikimedia-pageviews", "google-trends-kr-rss"],
           "config": {"series_days": SERIES_DAYS, "base_days": BASE_DAYS, "min_base": MIN_BASE,
                      "z_watch": Z_WATCH, "articles": list(ARTICLES), "keywords": list(KEYWORDS),
                      "method": "daily counts vs preceding 28 calendar days; median/MAD * 1.4826",
                      "trends_hits": "matching item titles and news titles; one hit per matching title"},
           "status": status, "alerts": [], "watch": watch, **results}
    if errors:
        out["error"] = errors
    write_json(out)
    lines += [f"주의: {item}" for item in watch]
    lines += [f"판정: {status}", f"출처: Wikimedia Pageviews · Google Trends KR RSS · {NOTICE}"]
    return [], lines


if __name__ == "__main__":
    alerts, lines = run()
    print(*lines, sep="\n")
