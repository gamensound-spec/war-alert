"""주한미군·공관 관련 공개 보도 건수. 실제 움직임을 추적하지 않는 참고 지표."""
import csv
import datetime as dt
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

from attention_monitor import atomic_write
from news_monitor import robust_z

API = "https://news.google.com/rss/search"
GROUPS = {
    "evac": {"label": "비전투원 후송", "queries": [
        {"q": '("noncombatant evacuation" OR "ordered departure" OR "authorized departure" OR NEO) (Korea OR USFK) when:7d',
         "hl": "en-US", "gl": "US", "ceid": "US:en"},
        {"q": "주한미군 (비전투원 OR 소개 OR 철수) when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}]},
    "readiness": {"label": "경계태세", "queries": [
        {"q": '("force protection condition" OR FPCON OR "heightened alert" OR "alert status") (USFK OR "U.S. Forces Korea") when:7d',
         "hl": "en-US", "gl": "US", "ceid": "US:en"}]},
    "families": {"label": "가족·이동", "queries": [
        {"q": '("military families" OR dependents OR "PCS") Korea (evacuate OR relocate OR suspend OR freeze) when:7d',
         "hl": "en-US", "gl": "US", "ceid": "US:en"}]},
}
BASE_DAYS, MIN_BASE, Z_WATCH = 28, 14, 2.0
EVAC_HITS, EVAC_SOURCES, GROUP_DELAY = 3, 2, 2
JSON_FILE, CSV_FILE = "data/usfk.json", "data/usfk_log.csv"
FIELDS = ["date", "group", "hits_24h", "hits_7d", "training_7d"]
KST = dt.timezone(dt.timedelta(hours=9))
NOTICE = "참고 지표 · 신뢰도 낮음 · 경보 없음"
# 구글 검색이 넓게 걸리므로(예: NEO → Neoprints) 제목에 주제어와 주한미군·공관 맥락이 모두 있어야 센다.
CONTEXT = re.compile(r"USFK|Forces Korea|주한\s?미군|미군|대사관|embassy|U\.S\. citizens|Americans in|미국\s?시민|미국인", re.IGNORECASE)
TOPIC = {
    "evac": [re.compile(r"non-?combatant|evacuat|ordered departure|authorized departure|(?-i:\bNEO\b)|비전투원|후송|소개령|대피|철수", re.IGNORECASE)],
    "readiness": [re.compile(r"force protection|FPCON|heightened alert|alert status|경계\s?태세|방호\s?태세|위기\s?경보|워치콘", re.IGNORECASE)],
    "families": [re.compile(r"famil|dependents|(?-i:\bPCS\b)|가족", re.IGNORECASE),
                 re.compile(r"evacuat|relocat|suspend|freeze|철수|대피|이주|중단|동결", re.IGNORECASE)],
}
TRAINING = re.compile(r"exercise|drill|training|훈련", re.IGNORECASE)
FAILURES = (requests.RequestException, RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError)


def safe_link(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return ""
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme.lower() in ("http", "https") and parsed.netloc else ""
    except ValueError:
        return ""


def parse_rss(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("Google News RSS XML 형식 오류") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Google News RSS channel 없음")
    articles = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title", default="").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", default=""))
            published = published.replace(tzinfo=dt.timezone.utc) if published.tzinfo is None else published
        except (TypeError, ValueError, OverflowError):
            continue
        if not title:
            continue
        articles.append({"title": title, "link": safe_link(item.findtext("link", default="").strip()),
                         "date": published.astimezone(KST).isoformat(timespec="seconds"),
                         "source": item.findtext("source", default="").strip(),
                         "training": bool(TRAINING.search(title))})
    return articles


def relevant(group, title):
    return bool(CONTEXT.search(title)) and all(rule.search(title) for rule in TOPIC[group])


def fetch(group):
    articles = []
    for query in GROUPS[group]["queries"]:
        response = requests.get(API, params=query, headers={"User-Agent": "war-alert/1.0"}, timeout=30)
        response.raise_for_status()
        articles.extend(parse_rss(response.text))
    return [item for item in articles if relevant(group, item["title"])]


def snapshot(articles, now):
    # 최신 중복을 남긴다. 두 언어 검색 결과도 그룹 안에서는 제목 단위로 한 번만 센다.
    unique = {}
    for article in sorted(articles, key=lambda item: item["date"], reverse=True):
        published = dt.datetime.fromisoformat(article["date"])
        if now - dt.timedelta(days=7) <= published <= now:
            unique.setdefault(article["title"].lower()[:60], article)
    stress = [item for item in unique.values() if not item["training"]]
    recent = [item for item in stress if dt.datetime.fromisoformat(item["date"]) >= now - dt.timedelta(days=1)]
    sources = {item["source"].casefold() for item in recent if item["source"]}
    return {"hits_24h": len(recent), "hits_7d": len(stress),
            "training_7d": sum(item["training"] for item in unique.values()),
            "sources_24h": len(sources)}, stress


def read_log():
    if not Path(CSV_FILE).exists():
        return []
    with open(CSV_FILE, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError("보도 스냅샷 CSV 열 불일치")
        rows = []
        for row in reader:
            date = dt.date.fromisoformat(row["date"]).isoformat()
            if row["group"] not in GROUPS:
                raise ValueError("보도 스냅샷 CSV 그룹 불일치")
            values = {key: int(row[key]) for key in FIELDS[2:]}
            if any(value < 0 for value in values.values()):
                raise ValueError("보도 스냅샷 CSV 음수 건수")
            rows.append({"date": date, "group": row["group"], **values})
    return upsert(rows, [])


def upsert(rows, updates):
    days = {(row["date"], row["group"]): row for row in [*rows, *updates]}
    return [days[key] for key in sorted(days)]


def write_log(rows):
    def writer(f):
        output = csv.DictWriter(f, fieldnames=FIELDS)
        output.writeheader()
        output.writerows(rows)
    atomic_write(CSV_FILE, writer)


def evaluate(group, item, rows, date):
    start = (dt.date.fromisoformat(date) - dt.timedelta(days=BASE_DAYS)).isoformat()
    # 같은 그룹의 하루 건수끼리만 비교한다. 7일 건수·훈련 건수·당일은 기준선에서 제외한다.
    base = [row["hits_24h"] for row in rows if row["group"] == group and start <= row["date"] < date]
    median, z = robust_z(item["hits_24h"], base) if len(base) >= MIN_BASE else (None, None)
    if z is not None and not math.isfinite(z):
        z = None
    status = "muted" if z is None else "watch" if z >= Z_WATCH else "normal"
    if len(base) >= MIN_BASE and group == "evac":
        status = "watch" if item["hits_24h"] >= EVAC_HITS and item["sources_24h"] >= EVAC_SOURCES else "normal"
    note = (f"판단 보류 · 기준선 {len(base)}/{MIN_BASE}일" if len(base) < MIN_BASE
            else f"z {z:+.2f}" if z is not None else f"평소 {median:g}건 대비 {item['hits_24h']}건 · MAD 0")
    return {**item, "date": date, "base_n": len(base), "median": median, "z": z, "status": status, "note": note}


def previous():
    try:
        data = json.loads(Path(JSON_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(out):
    atomic_write(JSON_FILE, lambda f: json.dump(out, f, ensure_ascii=False, indent=1, allow_nan=False))


def run(fetcher=fetch, now=None):
    now = (now or dt.datetime.now(KST)).astimezone(KST)
    date = now.date().isoformat()
    old = previous()
    groups, errors, lines, articles, updates = {}, {}, [], [], []
    try:
        rows = read_log()
        log_error = None
    except FAILURES as exc:
        rows, log_error = [], str(exc)
    for index, (group, config) in enumerate(GROUPS.items()):
        if index:
            time.sleep(GROUP_DELAY)
        label = config["label"]
        try:
            if log_error:
                raise ValueError(log_error)
            item, headlines = snapshot(fetcher(group), now)
            result = evaluate(group, item, rows, date)
            updates.append({"date": date, "group": group, **{key: item[key] for key in FIELDS[2:]}})
            articles.extend(headlines)
            line = (f"{label} {date}: 24시간 {item['hits_24h']}건 · 7일 {item['hits_7d']}건 · "
                    f"훈련 {item['training_7d']}건 제외 · 매체 {item['sources_24h']}곳 · {result['note']}")
        except FAILURES as exc:
            errors[group] = str(exc)
            prior = (old.get("groups") or {}).get(group) or {}
            result = {**prior, "status": "muted", "error": str(exc)}
            line = f"{label}: 수집 실패 · {exc} · " + ("직전 관측값 유지" if prior else "이전 관측값 없음")
        groups[group] = result
        lines.append(f"{line} · {NOTICE}")
    if updates:
        write_log(upsert(rows, updates))
    watch = [f"{GROUPS[group]['label']} 관련 공개 보도 증가 (24시간 {item['hits_24h']}건)"
             for group, item in groups.items() if item["status"] == "watch"]
    status = "watch" if watch else "normal" if all(item["status"] == "normal" for item in groups.values()) else "muted"
    if len(errors) == len(GROUPS):
        headlines = old.get("headlines") or []
    else:
        unique = {}
        for article in sorted(articles, key=lambda item: item["date"], reverse=True):
            unique.setdefault(article["title"].lower()[:60], {key: article[key] for key in ("title", "source", "date", "link")})
        headlines = list(unique.values())[:8]
    # 이전 JSON에서 가져온 링크도 출력 직전에 다시 제한한다.
    headlines = [{**item, "link": safe_link(item.get("link"))} for item in headlines[:8]]
    out = {"generated_at": now.isoformat(timespec="minutes"), "source": "google-news-rss",
           "config": {"groups": GROUPS, "base_days": BASE_DAYS, "min_base": MIN_BASE,
                      "z_watch": Z_WATCH, "evac_hits": EVAC_HITS, "evac_sources": EVAC_SOURCES,
                      "group_delay_seconds": GROUP_DELAY,
                      "method": "group hits_24h vs preceding 28 calendar days of same group hits_24h; median/MAD * 1.4826"},
           "status": status, "alerts": [], "watch": watch, "groups": groups, "headlines": headlines}
    if errors:
        out["error"] = errors
    write_json(out)
    lines += [f"주의: {item} · {NOTICE}" for item in watch]
    lines += [f"판정: {status} · {NOTICE}", f"출처: Google News RSS · {NOTICE}"]
    return [], lines


if __name__ == "__main__":
    alerts, lines = run()
    print(*lines, sep="\n")
