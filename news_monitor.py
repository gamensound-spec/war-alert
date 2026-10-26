"""
세계 언론 동향 모니터 (GDELT DOC 2.0, 키 불필요)
- 지표: 하루 전체 기사 중 한반도 분쟁 기사 비율 (만 건당)
- 이상치: 직전 28일 중앙값 대비 robust z-score (중앙값·MAD)
- GDELT 수집량 자체가 들쭉날쭉해서 건수가 아니라 비율로 본다
"""
import json, os, time, statistics, datetime as dt

import requests

QUERY = ('("north korea" OR "korean peninsula") '
         '(war OR missile OR attack OR invasion OR evacuation OR troops)')
API = "https://api.gdeltproject.org/api/v2/doc/doc"
BASE_DAYS = 28        # 기준선 기간
MIN_BASE = 14         # 기준선 표본이 이보다 적으면 판단 보류
Z_WATCH, Z_ALERT = 2.0, 3.0
RATIO_ALERT = 2.0     # 경보는 z와 함께 평소의 2배 이상일 때만
JSON_FILE = "data/news.json"
KST = dt.timezone(dt.timedelta(hours=9))


def gdelt(mode, **extra):
    """GDELT는 IP당 5초에 1회 제한. 거절되면 간격을 늘려 재시도"""
    params = {"query": QUERY, "mode": mode, "format": "json", **extra}
    for wait in (0, 15, 30, 60):
        time.sleep(wait or 10)
        r = requests.get(API, params=params, timeout=60)
        if r.status_code == 429:
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("GDELT 요청 제한(429)이 풀리지 않음")


def fetch():
    vol = gdelt("timelinevolraw", timespan="90d")["timeline"][0]["data"]
    # 논조·기사 목록은 부가 정보. 제한에 걸려도 판단은 계속한다
    try:
        tone = {d["date"][:8]: d["value"] for d in gdelt("timelinetone", timespan="90d")["timeline"][0]["data"]}
    except Exception as e:
        print(f"GDELT 논조 생략: {e}")
        tone = {}
    try:
        arts = gdelt("artlist", timespan="1d", maxrecords=30, sort="hybridrel").get("articles", [])
    except Exception as e:
        print(f"GDELT 기사 목록 생략: {e}")
        arts = []
    days = []
    for d in vol:
        k = d["date"][:8]
        days.append({"date": f"{k[:4]}-{k[4:6]}-{k[6:]}", "count": d["value"], "total": d["norm"],
                     "share": round(d["value"] / d["norm"] * 1e4, 3) if d["norm"] else None,
                     "tone": tone.get(k)})
    return days, arts


def robust_z(x, base):
    med = statistics.median(base)
    mad = statistics.median(abs(b - med) for b in base) * 1.4826
    return med, ((x - med) / mad if mad else None)


def evaluate(days):
    """수집이 덜 된 날(오늘 등)은 빼고, 마지막 온전한 날을 판단한다"""
    totals = [d["total"] for d in days if d["total"]]
    full = statistics.median(totals) * 0.5 if totals else 0
    for d in days:   # 사이트 그래프에서도 덜 수집된 날은 뺀다
        d["partial"] = not d["total"] or d["total"] < full
    ok = [d for d in days if d["share"] is not None and not d["partial"]]
    if not ok:
        raise RuntimeError("GDELT 일별 데이터가 비어 있음")
    last = ok[-1]
    base = [d["share"] for d in ok[:-1]][-BASE_DAYS:]
    latest = {"date": last["date"], "share": last["share"], "count": last["count"],
              "tone": last["tone"], "base_n": len(base), "median": None, "ratio": None, "z": None}
    if len(base) >= MIN_BASE:
        med, z = robust_z(last["share"], base)
        latest.update(median=round(med, 3), ratio=round(last["share"] / med, 2) if med else None,
                      z=round(z, 2) if z is not None else None)
    alerts, watch, lines = [], [], []
    s = f"{last['date']}: 관련 기사 {last['count']}건, 만 건당 {last['share']:.1f}"
    if latest["z"] is None:
        lines.append(s + f" | 판단 보류(기준선 {len(base)}/{MIN_BASE}일)")
    else:
        lines.append(s + f" (평소 {latest['median']:.1f}, {latest['ratio']:.1f}배) | z {latest['z']:+.2f}"
                     + (f" | 논조 {last['tone']:+.1f}" if last["tone"] is not None else ""))
        if latest["z"] >= Z_ALERT and (latest["ratio"] or 0) >= RATIO_ALERT:
            alerts.append(f"한반도 분쟁 기사량 급증: 평소의 {latest['ratio']:.1f}배 (z {latest['z']:+.1f})")
        elif latest["z"] >= Z_WATCH:
            watch.append(f"기사량 증가: 평소의 {latest['ratio']:.1f}배 (z {latest['z']:+.1f})")
    lines += [f"주의: {w}" for w in watch]
    return alerts, watch, lines, latest


def articles(arts, n=12):
    out, seen = [], set()
    for a in arts:
        t = (a.get("title") or "").strip()
        key = t.lower()[:60]
        if not t or key in seen:
            continue
        seen.add(key)
        s = a.get("seendate", "")
        out.append({"title": t, "url": a.get("url"), "domain": a.get("domain"),
                    "language": a.get("language"), "country": a.get("sourcecountry"),
                    "date": f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else None})
        if len(out) == n:
            break
    return out


def run(fetcher=fetch):
    days, arts = fetcher()
    alerts, watch, lines, latest = evaluate(days)
    os.makedirs("data", exist_ok=True)
    out = {
        "generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
        "query": QUERY,
        "config": {"base_days": BASE_DAYS, "min_base": MIN_BASE, "z_watch": Z_WATCH,
                   "z_alert": Z_ALERT, "ratio_alert": RATIO_ALERT},
        "alerts": alerts, "watch": watch, "latest": latest,
        "series": days, "articles": articles(arts),
    }
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return alerts, lines


if __name__ == "__main__":
    a, l = run()
    print(*(a + l), sep="\n")
