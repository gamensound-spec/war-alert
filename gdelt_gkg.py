"""GDELT GKG 원본을 메모리에서 읽고 UTC 일별 집계만 보관한다."""
import argparse
import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import unquote_plus, urlsplit
import zipfile

import requests

BASE_URL = "https://data.gdeltproject.org/gdeltv2"
CSV_FILE = Path("data/news_gkg_daily.csv")
JSON_FILE = Path("data/news.json")
MAX_DAYS = 3
HISTORY_DAYS = 29  # 최신 하루 + 직전 28일 기준선
ARTICLE_LIMIT = 12
# GKG 2.1: DocumentIdentifier(5), V2EnhancedThemes(9), V1.5Tone(16).
DOCUMENT, THEMES, TONE = 4, 8, 15
REGION = re.compile(r"\b(?:north korea|korean peninsula)\b")
CONFLICT = re.compile(r"\b(?:war|missile|attack|invasion|evacuation|troops)\b")


def day_urls(day):
    """masterfilelist 전체를 받지 않고 날짜 규칙으로 96개 URL을 만든다."""
    return [f"{BASE_URL}/{day:%Y%m%d}{hour:02d}{minute:02d}00.gkg.csv.zip"
            for hour in range(24) for minute in range(0, 60, 15)]


def aggregate(lines):
    """헤더 없는 TSV를 줄 단위로 처리한다. 전체 행/URL 목록은 보관하지 않는다."""
    total = count = tone_n = 0
    tone_sum = 0.0
    arts, seen = [], set()
    for line in lines:
        if not line.strip():
            continue
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) != 27:
            raise RuntimeError(f"GKG 컬럼 수 오류: {len(fields)} (예상 27)")
        total += 1
        url = fields[DOCUMENT]
        text = re.sub(r"[^a-z0-9]+", " ",
                      unquote_plus(fields[THEMES] + " " + url).lower())
        if not (REGION.search(text) and CONFLICT.search(text)):
            continue
        count += 1
        raw_tone = fields[TONE].split(",", 1)[0]
        if raw_tone:
            try:
                tone = float(raw_tone)
            except ValueError as exc:
                raise RuntimeError("GKG 논조 값 오류") from exc
            if not math.isfinite(tone):
                raise RuntimeError("GKG 논조 값 오류: 유한한 수가 아님")
            tone_sum += tone
            tone_n += 1
        parsed = urlsplit(url)
        if (len(arts) < ARTICLE_LIMIT and url not in seen
                and parsed.scheme in ("http", "https") and parsed.netloc):
            seen.add(url)
            # GKG에는 기사 제목 컬럼이 없다. 원문 사이트에 추가 요청하지 않는다.
            arts.append({"title": f"{parsed.netloc} | {url}", "url": url,
                         "domain": parsed.netloc, "language": "English",
                         "seendate": fields[1], "source": "gdelt-gkg"})
    return {"count": count, "total": total, "tone_sum": tone_sum,
            "tone_n": tone_n, "articles": arts}


def download_day(day, session, metrics):
    started = time.monotonic()
    count = total = tone_n = 0
    tone_sum = 0.0
    arts, seen = [], set()
    before = metrics["bytes"]
    for index, url in enumerate(day_urls(day), 1):
        try:
            # 압축 파일 하나만 RAM에 담고, 해제한 TSV는 스트리밍 파싱한다.
            # ZipFile의 중앙 디렉터리 탐색 때문에 seek 가능한 메모리 버퍼를 쓴다.
            with session.get(url, stream=True, timeout=(15, 90),
                             allow_redirects=True) as response:
                response.raise_for_status()
                with io.BytesIO() as compressed:
                    for chunk in response.iter_content(chunk_size=65536):
                        metrics["bytes"] += len(chunk)
                        compressed.write(chunk)
                    compressed.seek(0)
                    with zipfile.ZipFile(compressed) as archive:
                        members = archive.namelist()
                        if len(members) != 1 or not members[0].endswith(".gkg.csv"):
                            raise RuntimeError("GKG ZIP 구성 오류")
                        with archive.open(members[0]) as member:
                            with io.TextIOWrapper(member, encoding="utf-8", errors="replace") as lines:
                                part = aggregate(lines)
        except (requests.RequestException, zipfile.BadZipFile, UnicodeError,
                EOFError, ValueError, OSError, RuntimeError) as exc:
            raise RuntimeError(f"GKG 수집 실패 ({url}): {exc}") from exc
        count += part["count"]
        total += part["total"]
        tone_sum += part["tone_sum"]
        tone_n += part["tone_n"]
        for article in part["articles"]:
            if len(arts) < ARTICLE_LIMIT and article["url"] not in seen:
                seen.add(article["url"])
                arts.append(article)
        if index % 24 == 0:
            print(f"GKG {day}: {index}/96 files", flush=True)
    if not total:
        raise RuntimeError(f"GKG 일별 데이터가 비어 있음: {day}")
    row = {"date": day.isoformat(), "count": count, "total": total,
           "tone": tone_sum / tone_n if tone_n else None}
    print(f"GKG {day}: count={count} total={total} tone={row['tone']} "
          f"bytes={metrics['bytes'] - before} elapsed={time.monotonic() - started:.2f}s",
          flush=True)
    return row, arts


def load_daily(path):
    if not path.exists():
        return {}
    rows = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = dt.date.fromisoformat(row["date"]).isoformat()
            rows[day] = {"date": day, "count": int(row["count"]),
                         "total": int(row["total"]),
                         "tone": float(row["tone"]) if row["tone"] else None}
    return rows


def save_daily(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "count", "total", "tone"])
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))
    temporary.replace(path)


def fetch(backfill=MAX_DAYS, today=None, csv_file=None, json_file=None, metrics=None):
    """최근 누락일부터 최대 3일을 추가하고 GKG 단독 기준선으로 쓴다."""
    if not 1 <= backfill <= MAX_DAYS:
        raise ValueError(f"backfill은 1~{MAX_DAYS}일이어야 함")
    today = today or dt.datetime.now(dt.timezone.utc).date()
    csv_file = Path(csv_file) if csv_file is not None else CSV_FILE
    json_file = Path(json_file) if json_file is not None else JSON_FILE
    metrics = metrics if metrics is not None else {"bytes": 0}
    cache = load_daily(csv_file)
    previous = json.loads(json_file.read_text(encoding="utf-8")) if json_file.exists() else {}
    # DOC 과거 series는 섞지 않는다: 매칭 범위가 달라 비율 기준선이 호환되지 않음(GKG 단독 기준선)
    days = {}
    # 이미 저장된 GKG 기사만 재사용한다. 오래된 백필 기사가 최신 기사를 덮지 않는다.
    arts = []
    if previous.get("source") == "gdelt-gkg":
        for article in previous.get("articles", []):
            arts.append({**article, "seendate": (article.get("date") or "").replace("-", ""),
                         "source": "gdelt-gkg"})
    missing = [today - dt.timedelta(days=offset) for offset in range(1, HISTORY_DAYS + 1)
               if (today - dt.timedelta(days=offset)).isoformat() not in cache][:backfill]
    newest = max((article.get("date") or "" for article in arts), default="")
    with requests.Session() as session:
        for day in missing:
            row, new_arts = download_day(day, session, metrics)
            cache[row["date"]] = row
            save_daily(cache, csv_file)  # 96개 전부 성공한 날만 체크포인트로 저장
            if row["date"] >= newest:
                newest = row["date"]
                arts = new_arts
    for key, row in cache.items():
        if key < today.isoformat():
            days[key] = {**row, "share": round(row["count"] / row["total"] * 1e4, 3)
                         if row["total"] else None, "source": "gdelt-gkg"}
    if not cache or max(key for key in cache) < (today - dt.timedelta(days=3)).isoformat():
        raise RuntimeError("GKG 최신 일별 데이터가 없거나 3일 넘게 지연됨")
    return [days[key] for key in sorted(days)], arts[:ARTICLE_LIMIT]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", type=int, choices=range(1, MAX_DAYS + 1),
                        default=MAX_DAYS, help="실행당 누락일 수 (최대 3, 기본 3)")
    args = parser.parse_args()
    metrics = {"bytes": 0}
    started = time.monotonic()
    try:
        days, arts = fetch(backfill=args.backfill, metrics=metrics)
        # DOC API를 재호출하지 않고 기존 출력 스키마와 평가 함수를 사용한다.
        import news_monitor
        news_monitor.run(fetcher=lambda: (days, arts))
    finally:
        elapsed = time.monotonic() - started
        print(f"GKG run: bytes={metrics['bytes']} "
              f"MiB={metrics['bytes'] / 1024 ** 2:.2f} elapsed={elapsed:.2f}s", flush=True)


if __name__ == "__main__":
    main()
