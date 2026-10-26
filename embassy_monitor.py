"""
주한 대사관·여행경보 모니터
- 수집: 미 국무부 Travel Advisory, 영국 FCDO, 캐나다, 일본 외무성(위험정보·영사메일),
        호주 Smartraveller, 주한 미국대사관 Alert RSS
- 경보: 여행경보 단계 상승 / 공통 단계 3 이상 지속 / 새 공지에 철수·출국 권고 키워드
- 주의: 새 공지에 북한·미사일·군사 등 키워드 (리포트에만 표시)
- 출력: data/embassy.json(사이트용), data/embassy_state.json(직전 상태), data/embassy_log.csv(누적)
"""
import os, re, csv, json, html, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

STATE_FILE = "data/embassy_state.json"
LOG_FILE = "data/embassy_log.csv"
JSON_FILE = "data/embassy.json"
RECENT_DAYS = 30
SEEN_MAX = 400

KST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

# 공통 단계 (1~4): 각국 체계를 대략 맞춘 값. 원래 단계 문구는 level_text에 그대로 둔다.
NORM_KO = {1: "일반 주의", 2: "주의 강화", 3: "여행 재고·필수 외 자제", 4: "여행 금지·철수"}

# ───────── 키워드 ─────────
CRITICAL = re.compile("|".join([
    r"ordered departure", r"authori[sz]ed departure", r"evacuat",
    r"leave (south )?korea", r"leave the country", r"depart (south )?korea",
    r"while commercial (flights|options)", r"suspend\w* (routine |all )?(consular )?(services|operations)",
    r"embassy (is |will be )?closed", r"closure of the (u\.s\. )?embassy",
    r"退避", r"出国(を|の)?(検討|勧告|推奨|お勧め)", r"早期(の)?(出国|帰国)", r"帰国(を|の)?(検討|勧告)",
    r"渡航(は)?(止め|中止)", r"大使館.{0,10}閉鎖", r"商用(便|定期便).{0,20}(運航|利用)",
]), re.I)
WATCH = re.compile("|".join([
    r"north korea", r"\bdprk\b", r"missile", r"military", r"nuclear", r"shelter",
    r"air raid", r"artillery", r"heightened tension", r"armistice",
    r"北朝鮮", r"ミサイル", r"核実験", r"核兵器", r"軍事", r"砲撃", r"武力", r"空襲", r"シェルター",
]), re.I)
SUPPRESS = re.compile(r"drill|exercise|routine message|훈련|訓練|演習", re.I)   # 민방위훈련 등
GLOBAL = re.compile(r"worldwide caution", re.I)                                 # 한국 특정 아님


def classify(title, text=""):
    t = f"{title} {text}"
    if SUPPRESS.search(title):
        return None
    if CRITICAL.search(t):
        return "watch" if GLOBAL.search(title) else "critical"
    if WATCH.search(t):
        return "watch"
    return None


# ───────── HTTP ─────────
def get(url, **kw):
    last = None
    for _ in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=40, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
    raise last


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def iso(d):
    return d.astimezone(KST).isoformat(timespec="minutes") if d else None


# ───────── 소스별 수집 ─────────
# 각 함수는 {"level", "level_norm", "level_text", "updated", "url", "items": [{id,date,title,text,url}]}를 돌려준다.
# level이 없는 소스(공지 피드)는 level 관련 값이 None.

def src_us_state():
    data = get("https://cadataapi.state.gov/api/TravelAdvisories").json()
    a = next(x for x in data if "KS" in x.get("Category", "") and "South Korea" in x.get("Title", ""))
    m = re.search(r"Level (\d)", a["Title"])
    lv = int(m.group(1)) if m else None
    upd = dt.datetime.fromisoformat(a["Updated"])
    return {
        "level": lv, "level_norm": lv, "level_text": a["Title"].split(":", 1)[-1].strip(),
        "updated": iso(upd), "url": a["Link"],
        "items": [{"id": a["Updated"], "date": iso(upd), "title": a["Title"],
                   "text": strip_tags(a.get("Summary"))[:2000], "url": a["Link"]}],
    }


UK_STATUS = [  # (alert_status 값, 공통 단계, 문구) — 심한 것부터
    ("avoid_all_travel_to_whole_country", 4, "Advise against all travel (whole country)"),
    ("avoid_all_but_essential_travel_to_whole_country", 3, "Advise against all but essential travel (whole country)"),
    ("avoid_all_travel_to_parts", 2, "Advise against all travel to parts"),
    ("avoid_all_but_essential_travel_to_parts", 2, "Advise against all but essential travel to parts"),
]


def src_uk():
    url = "https://www.gov.uk/foreign-travel-advice/south-korea"
    d = get("https://www.gov.uk/api/content/foreign-travel-advice/south-korea").json()
    det = d["details"]
    st = det.get("alert_status") or []
    lv, txt = 1, "No FCDO travel warning"
    for key, n, t in UK_STATUS:
        if key in st:
            lv, txt = n, t
            break
    items = [{"id": h["public_timestamp"], "date": iso(dt.datetime.fromisoformat(h["public_timestamp"].replace("Z", "+00:00"))),
              "title": h["note"].strip(), "text": "", "url": url}
             for h in det.get("change_history", [])[:20]]
    return {"level": lv, "level_norm": lv, "level_text": txt,
            "updated": iso(dt.datetime.fromisoformat(d["public_updated_at"])), "url": url, "items": items}


CA_TEXT = {0: "Exercise normal security precautions", 1: "Exercise a high degree of caution",
           2: "Avoid non-essential travel", 3: "Avoid all travel"}


def src_canada():
    k = get("https://data.international.gc.ca/travel-voyage/index-alpha-eng.json").json()["data"]["KR"]
    st = int(k["advisory-state"])
    upd = dt.datetime.fromisoformat(k["date-published"]["asp"][:19]).replace(
        tzinfo=dt.timezone(dt.timedelta(hours=-4)))   # asp 값은 동부시간. 일 단위 비교라 서머타임 오차는 무시
    url = "https://travel.gc.ca/destinations/south-korea"
    note = k["eng"].get("recent-updates") or ""
    return {"level": st, "level_norm": st + 1, "level_text": k["eng"].get("advisory-text") or CA_TEXT.get(st),
            "updated": iso(upd), "url": url,
            "items": [{"id": k["date-published"]["date"], "date": iso(upd), "title": note, "text": "", "url": url}] if note else []}


JP_TEXT = {0: "危険情報なし", 1: "レベル1 十分注意", 2: "レベル2 不要不急の渡航中止",
           3: "レベル3 渡航中止勧告", 4: "レベル4 退避勧告"}


def src_japan():
    r = get("https://www.ezairyu.mofa.go.jp/opendata/country/0082A.xml")
    root = ET.fromstring(r.content)
    lv = max([n for n in (4, 3, 2, 1) if (root.findtext(f"riskLevel{n}") or "0").strip() == "1"], default=0)
    items = []
    for m in root.findall("mail"):
        if not (m.findtext("infoName") or "").startswith("領事メール"):
            continue
        d = dt.datetime.strptime(m.findtext("leaveDate"), "%Y/%m/%d %H:%M:%S").replace(tzinfo=KST)
        items.append({"id": m.findtext("keyCd"), "date": iso(d), "title": m.findtext("title") or "",
                      "text": (m.findtext("lead") or "")[:1000], "url": m.findtext("infoUrl")})
    lm = root.get("lastModified")
    upd = dt.datetime.strptime(lm, "%Y/%m/%d %H:%M:%S").replace(tzinfo=KST) if lm else None
    return {"level": lv, "level_norm": min(4, lv + 1), "level_text": JP_TEXT[lv],
            "updated": iso(upd), "url": (root.findtext("riskUrl") or "").strip() or root.findtext("infoUrl"),
            "items": items}


AU_LEVELS = [("Do not travel", 4), ("Reconsider your need to travel", 3),
             ("Exercise a high degree of caution", 2), ("Exercise normal safety precautions", 1)]


def src_australia():
    # 로컬 환경에서 접속 불가로 미검증. 페이지 문구에서 단계 문장을 찾는다.
    url = "https://www.smartraveller.gov.au/destinations/asia/south-korea"
    text = strip_tags(get(url).text)
    i = text.lower().find("overall advice level")
    scope = text[i:i + 400] if i >= 0 else text
    found = [(scope.lower().find(p.lower()), p, n) for p, n in AU_LEVELS if p.lower() in scope.lower()]
    if not found:
        raise ValueError("단계 문구를 찾지 못함 (페이지 구조 변경 가능)")
    _, p, n = min(found)
    return {"level": n, "level_norm": n, "level_text": p, "updated": None, "url": url, "items": []}


def src_us_embassy():
    url = "https://kr.usembassy.gov/category/alert/"
    root = ET.fromstring(get("https://kr.usembassy.gov/category/alert/feed/").content)
    items = []
    for it in root.iter("item"):
        d = parsedate_to_datetime(it.findtext("pubDate"))
        items.append({"id": it.findtext("guid") or it.findtext("link"), "date": iso(d),
                      "title": it.findtext("title") or "",
                      "text": strip_tags(it.findtext("description"))[:1000], "url": it.findtext("link")})
    upd = max((i["date"] for i in items), default=None)
    return {"level": None, "level_norm": None, "level_text": None, "updated": upd, "url": url, "items": items}


SOURCES = [
    {"id": "us_state", "name": "미 국무부 여행경보", "fn": src_us_state},
    {"id": "uk_fcdo", "name": "영국 FCDO", "fn": src_uk},
    {"id": "canada", "name": "캐나다 여행경보", "fn": src_canada},
    {"id": "japan", "name": "일본 외무성 위험정보·영사메일", "fn": src_japan},
    {"id": "australia", "name": "호주 Smartraveller", "fn": src_australia},
    {"id": "us_embassy", "name": "주한 미국대사관 Alert", "fn": src_us_embassy},
]


# ───────── 판정 ─────────
def evaluate(results, state, today):
    """results: {id: 수집결과 또는 {"error": ...}}. state를 갱신하고 (alerts, lines, recent, rows)를 돌려준다."""
    alerts, lines, recent, rows = [], [], [], []
    cutoff = (dt.datetime.combine(today, dt.time(), KST) - dt.timedelta(days=RECENT_DAYS)).isoformat()
    for s in SOURCES:
        sid, name, r = s["id"], s["name"], results[s["id"]]
        prev = state.get(sid)
        if "error" in r:
            lines.append(f"{name}: 수집 실패 ({r['error'][:120]})")
            rows.append({"source": sid, "name": name, "error": r["error"][:200],
                         **{k: (prev or {}).get(k) for k in ("level", "level_norm", "level_text", "updated")},
                         "url": (prev or {}).get("url"), "changed": None})
            continue

        first = prev is None
        prev = prev or {"seen": []}
        changed = None
        if r["level"] is not None:
            tag = f"{name}: {r['level_text']} (공통 {r['level_norm']}단계·{NORM_KO[r['level_norm']]})"
            if not first and prev.get("level") is not None and r["level"] != prev["level"]:
                changed = "up" if r["level"] > prev["level"] else "down"
                arrow = f"{prev.get('level_text')} → {r['level_text']}"
                if changed == "up":
                    alerts.append(f"{name} 단계 상승: {arrow}")
                else:
                    lines.append(f"{name} 단계 하향: {arrow}")
            if r["level_norm"] >= 3 and changed != "up":
                alerts.append(f"{tag} — 높은 단계 지속")
            lines.append(tag)
        elif r["items"]:
            last = max(r["items"], key=lambda i: i["date"] or "")
            lines.append(f"{name}: 최근 공지 [{(last['date'] or '?')[:10]}] {last['title']}")
        if not first and r["updated"] and prev.get("updated") and r["updated"] != prev["updated"]:
            lines.append(f"{name}: 본문 갱신 {r['updated'][:10]}")

        seen = set(prev.get("seen", []))
        for it in r["items"]:
            sev = classify(it["title"], it["text"])
            new = it["id"] not in seen
            if sev and it["date"] and it["date"] >= cutoff:
                recent.append({"source": name, "date": it["date"], "title": it["title"],
                               "url": it["url"], "severity": sev})
            if new and not first:
                lines.append(f"{name} 새 공지 [{it['date'][:10] if it['date'] else '?'}] {it['title']}"
                             + {"critical": "  ← 철수·출국 키워드", "watch": "  ← 주의 키워드"}.get(sev, ""))
                if sev == "critical":
                    alerts.append(f"{name} 새 공지: {it['title']} ({it['url']})")

        state[sid] = {"level": r["level"], "level_norm": r["level_norm"], "level_text": r["level_text"],
                      "updated": r["updated"], "url": r["url"],
                      "seen": ([i["id"] for i in r["items"]] + [x for x in prev.get("seen", [])
                               if x not in {i["id"] for i in r["items"]}])[:SEEN_MAX]}
        latest = max(r["items"], key=lambda i: i["date"] or "", default=None)
        rows.append({"source": sid, "name": name, "error": None, "level": r["level"], "level_norm": r["level_norm"],
                     "level_text": r["level_text"], "updated": r["updated"], "url": r["url"], "changed": changed,
                     "latest": {k: latest[k] for k in ("date", "title", "url")} if latest else None})

    # 같은 제목(영사메일 1보·2보 중복 등)은 한 번만
    uniq, keys = [], set()
    for x in sorted(recent, key=lambda x: x["date"], reverse=True):
        k = (x["source"], re.sub(r"[（(].*?[）)]|について|\s", "", x["title"]), x["date"][:10])
        if k not in keys:
            keys.add(k); uniq.append(x)
    return alerts, lines, uniq, rows


# ───────── 저장 ─────────
def append_log(rows, today):
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["date", "source", "level", "level_norm", "level_text", "updated", "error"])
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({"date": today.isoformat(), **{k: r.get(k) for k in w.fieldnames if k != "date"}})


def export_json(rows, alerts, recent, today):
    out = {
        "generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
        "today": today.isoformat(), "recent_days": RECENT_DAYS, "norm_labels": NORM_KO,
        "alerts": alerts, "sources": rows, "recent": recent[:40],
        "counts": {"critical": sum(x["severity"] == "critical" for x in recent),
                   "watch": sum(x["severity"] == "watch" for x in recent)},
    }
    with open(JSON_FILE, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)


def run(today=None, fetchers=None):
    """수집·판정·저장. (alerts, lines)를 돌려준다. 메일은 daily_report.py가 묶어서 보낸다."""
    today = today or dt.datetime.now(KST).date()
    os.makedirs("data", exist_ok=True)
    fetchers = fetchers or {s["id"]: s["fn"] for s in SOURCES}
    results = {}
    for s in SOURCES:
        try:
            results[s["id"]] = fetchers[s["id"]]()
        except Exception as e:
            results[s["id"]] = {"error": f"{type(e).__name__}: {e}"}
    state = json.load(open(STATE_FILE, encoding="utf-8")) if os.path.exists(STATE_FILE) else {}
    alerts, lines, recent, rows = evaluate(results, state, today)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(state, fp, ensure_ascii=False, indent=1)
    append_log(rows, today)
    export_json(rows, alerts, recent, today)
    c = sum(x["severity"] == "critical" for x in recent)
    w = sum(x["severity"] == "watch" for x in recent)
    lines.append(f"최근 {RECENT_DAYS}일 키워드 공지: 철수·출국 {c}건 / 주의 {w}건")
    return alerts, lines


if __name__ == "__main__":
    a, l = run()
    print("🚨 경보\n" + "\n".join(a) if a else "이상 없음", "", *l, sep="\n")
