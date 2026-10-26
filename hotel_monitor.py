"""
남산 그랜드 하얏트 가격 이상치 모니터
- 수집: SerpApi Google Hotels (1회 검색 = 여러 호텔 가격)
- 지표: ratio = 하얏트 가격 / 대조군 중앙값
- 이상치: 같은 체크인 요일·같은 선행일수 과거 분포 대비 z-score
- 출력: 일 단위 그래프 + Gmail 리포트
"""
import os, sys, smtplib, statistics, datetime as dt
from html import escape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ───────── 설정 ─────────
TARGET = {"name": "Grand Hyatt Seoul", "keys": ["grand hyatt seoul", "그랜드 하얏트 서울"]}
CONTROLS = [
    {"name": "The Shilla Seoul",    "keys": ["shilla seoul", "서울신라", "신라호텔"]},
    {"name": "Banyan Tree Seoul",   "keys": ["banyan tree", "반얀트리"]},
    {"name": "Four Seasons Seoul",  "keys": ["four seasons", "포시즌스"]},
    {"name": "JW Marriott Seoul",   "keys": ["jw marriott hotel seoul", "jw marriott seoul", "jw 메리어트 서울"]},
]
SEARCH_QUERY = "Seoul 5 star hotels Namsan Yongsan"
OFFSETS = [1, 3, 7]          # 체크인 선행일수 → 하루 3회, 월 약 90회 (무료 250회 이내)
Z_ALERT = 2.5                # 이 이상이면 경보
MIN_HISTORY = 4              # 같은 요일 표본이 이 수 미만이면 z-score 보류
DATA_FILE = "data/hotel_prices.csv"
CHART_FILE = "data/hotel_chart.png"

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
MAIL_TO = os.environ.get("MAIL_TO", GMAIL_USER)

KST = dt.timezone(dt.timedelta(hours=9))


# ───────── 수집 ─────────
def fetch_properties(check_in: dt.date):
    params = {
        "engine": "google_hotels",
        "q": SEARCH_QUERY,
        "check_in_date": check_in.isoformat(),
        "check_out_date": (check_in + dt.timedelta(days=1)).isoformat(),
        "adults": 2,
        "currency": "KRW",
        "gl": "kr",
        "hl": "en",
        "hotel_class": "5",
        "api_key": SERPAPI_KEY,
    }
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=60)
    r.raise_for_status()
    return r.json().get("properties", [])


def match(props, hotel):
    for p in props:
        name = p.get("name", "").lower()
        if any(k in name for k in hotel["keys"]):
            price = (p.get("rate_per_night") or {}).get("extracted_lowest")
            return price  # None이면 검색엔 있으나 요금 없음(매진 가능)
    return "missing"      # 검색 결과에 미검출


def collect(today: dt.date, fetcher=fetch_properties):
    rows = []
    for off in OFFSETS:
        ci = today + dt.timedelta(days=off)
        props = fetcher(ci)
        for role, h in [("target", TARGET)] + [("control", c) for c in CONTROLS]:
            v = match(props, h)
            status = "missing" if v == "missing" else ("no_rate" if v is None else "ok")
            rows.append({
                "fetch_date": today.isoformat(), "checkin": ci.isoformat(),
                "offset": off, "weekday": ci.weekday(), "role": role,
                "hotel": h["name"], "price": v if status == "ok" else None,
                "status": status,
            })
    return pd.DataFrame(rows)


# ───────── 지표 ─────────
def daily_metrics(df):
    out = []
    for (fd, off), g in df.groupby(["fetch_date", "offset"]):
        t = g[g.role == "target"].iloc[0]
        ctrl = g[(g.role == "control") & (g.status == "ok")].price.astype(float)
        cmed = float(ctrl.median()) if len(ctrl) else None
        tp = float(t.price) if t.status == "ok" else None
        out.append({
            "fetch_date": fd, "offset": off, "weekday": int(g.weekday.iloc[0]),
            "target_price": tp, "target_status": t.status,
            "control_median": cmed, "control_n": len(ctrl),
            "ratio": tp / cmed if tp and cmed else None,
        })
    return pd.DataFrame(out).sort_values(["offset", "fetch_date"])


def zscore(m, col, row):
    hist = m[(m.offset == row.offset) & (m.weekday == row.weekday)
             & (m.fetch_date < row.fetch_date)][col].dropna()
    if len(hist) < MIN_HISTORY:
        return None, len(hist)
    sd = statistics.pstdev(hist)
    if sd == 0:
        return None, len(hist)
    return (row[col] - hist.mean()) / sd, len(hist)


def evaluate(m, today):
    alerts, lines = [], []
    for _, r in m[m.fetch_date == today].iterrows():
        tag = f"D+{r.offset} ({['월','화','수','목','금','토','일'][r.weekday]})"
        if r.target_status != "ok":
            msg = f"{tag}: 하얏트 요금 {'미노출(매진 가능)' if r.target_status=='no_rate' else '검색 미검출'}, 대조군 {r.control_n}곳 정상"
            lines.append(msg)
            if r.target_status == "no_rate" and r.control_n >= 2:
                alerts.append(msg)
            continue
        z_ratio, n = zscore(m, "ratio", r)
        z_ctrl, _ = zscore(m, "control_median", r)
        zr = f"{z_ratio:+.2f}" if z_ratio is not None else f"보류(표본 {n}/{MIN_HISTORY})"
        zc = f"{z_ctrl:+.2f}" if z_ctrl is not None else "보류"
        msg = (f"{tag}: 하얏트 ₩{r.target_price:,.0f} / 대조군 중앙 ₩{r.control_median:,.0f} "
               f"→ 비율 {r.ratio:.2f} | z(비율) {zr} | z(대조군) {zc}")
        lines.append(msg)
        if z_ratio is not None and z_ratio >= Z_ALERT:
            alerts.append(msg + "  ← 하얏트 단독 급등")
        elif z_ctrl is not None and z_ctrl >= Z_ALERT:
            alerts.append(msg + "  ← 서울 고급호텔 전반 급등 (행사 여부 확인)")
    return alerts, lines


# ───────── 사이트용 JSON ─────────
def export_json(df, m, alerts, today, path="data/metrics.json"):
    import json
    rows = []
    for _, r in m.iterrows():
        zr, n = zscore(m, "ratio", r) if pd.notna(r.ratio) else (None, 0)
        zc, _ = zscore(m, "control_median", r) if pd.notna(r.control_median) else (None, 0)
        f = lambda v: None if v is None or pd.isna(v) else round(float(v), 4)
        rows.append({
            "date": r.fetch_date, "offset": int(r.offset), "weekday": int(r.weekday),
            "target_price": f(r.target_price), "target_status": r.target_status,
            "control_median": f(r.control_median), "control_n": int(r.control_n),
            "ratio": f(r.ratio), "z_ratio": f(zr), "z_control": f(zc), "history_n": int(n),
        })
    latest = df[df.fetch_date == today.isoformat()]
    hotels = [{"offset": int(x.offset), "checkin": x.checkin, "hotel": x.hotel,
               "role": x.role, "price": None if pd.isna(x.price) else float(x.price),
               "status": x.status} for x in latest.itertuples()]
    out = {
        "generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "config": {"z_alert": Z_ALERT, "min_history": MIN_HISTORY, "offsets": OFFSETS,
                   "target": TARGET["name"], "controls": [c["name"] for c in CONTROLS]},
        "alerts": alerts, "series": rows, "latest_hotels": hotels,
    }
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)


# ───────── 그래프 ─────────
def plot(m, path):
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    for off, g in m.groupby("offset"):
        x = pd.to_datetime(g.fetch_date)
        axes[0].plot(x, g.target_price, marker="o", label=f"Hyatt D+{off}")
        axes[0].plot(x, g.control_median, ls="--", alpha=.6, label=f"Control median D+{off}")
        axes[1].plot(x, g.ratio, marker="o", label=f"D+{off}")
    axes[0].set_ylabel("KRW / night"); axes[0].legend(fontsize=7, ncol=2)
    axes[0].set_title("Grand Hyatt Seoul vs control hotels (daily)")
    axes[1].axhline(1, color="gray", lw=.8)
    axes[1].set_ylabel("Hyatt / control median"); axes[1].legend(fontsize=8)
    fig.autofmt_xdate(); fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)


# ───────── 메일 ─────────
def send_mail(subject, body, chart):
    msg = MIMEMultipart("related")
    msg["Subject"], msg["From"], msg["To"] = subject, GMAIL_USER, MAIL_TO
    has_chart = chart and os.path.exists(chart)
    html = ("<pre style='font-family:monospace;white-space:pre-wrap'>" + escape(body) + "</pre>"
            + ("<img src='cid:chart'>" if has_chart else ""))
    msg.attach(MIMEText(html, "html", "utf-8"))
    if has_chart:
        with open(chart, "rb") as f:
            img = MIMEImage(f.read()); img.add_header("Content-ID", "<chart>"); msg.attach(img)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD); s.send_message(msg)


def run(today=None, fetcher=fetch_properties, mail=True):
    today = today or dt.datetime.now(KST).date()
    os.makedirs("data", exist_ok=True)
    new = collect(today, fetcher)
    df = pd.concat([pd.read_csv(DATA_FILE), new]) if os.path.exists(DATA_FILE) else new
    df = df.drop_duplicates(["fetch_date", "offset", "hotel"], keep="last")
    df.to_csv(DATA_FILE, index=False)

    m = daily_metrics(df)
    alerts, lines = evaluate(m, today.isoformat())
    plot(m, CHART_FILE)
    export_json(df, m, alerts, today)
    head = "🚨 경보\n" + "\n".join(alerts) + "\n\n" if alerts else "이상 없음\n\n"
    body = head + "\n".join(lines)
    subject = f"[{'경보' if alerts else '일간'}] 남산 하얏트 지표 {today}"
    if mail:
        send_mail(subject, body, CHART_FILE)
    return subject, body


if __name__ == "__main__":
    print(*run(), sep="\n")
