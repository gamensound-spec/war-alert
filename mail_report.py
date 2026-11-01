"""
일간 메일 HTML. 각 모듈이 남긴 data/*.json을 읽어 표로 정리한다.
메일 앱은 <style>을 지우는 경우가 많아 스타일은 전부 인라인, 레이아웃은 table로 짠다.
"""
import json, statistics, datetime as dt
from html import escape

SITE = "https://reset589.com"
C = {"crit": "#d03b3b", "warn": "#e3a008", "good": "#1f9d55", "muted": "#8b8982"}
BG = {"crit": "#fbeaea", "warn": "#fdf5e1", "good": "#e6f4ec", "muted": "#efeee9"}
INK = {"crit": "#b02a2a", "warn": "#8a5d00", "good": "#17703d", "muted": "#55534e"}
LV = {1: ("good", "일반 주의"), 2: ("warn", "주의 강화"), 3: ("crit", "여행 재고"), 4: ("crit", "여행 금지·철수")}
FONT = "-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif"
Z_WARN, MIN_ALL = 1.5, 7     # 사이트(index.html)의 호텔 위험도 기준과 같게 유지


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def won(v):
    return "—" if v is None else f"₩{v:,.0f}"


def ymd(d):
    return f'<span style="white-space:nowrap">{d[2:10].replace("-", ".")}</span>' if d else ""


def sub(t):
    return f'<div style="font-size:11.5px;color:#8b8982;margin-top:2px">{t}</div>'


def lag(N, today):
    """GDELT 마지막 온전한 날이 오늘보다 며칠 뒤처졌는지"""
    return (dt.date.fromisoformat(today) - dt.date.fromisoformat(N["latest"]["date"])).days


def dot(k):
    return f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{C[k]};margin-right:6px"></span>'


def chip(k, t):
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;'
            f'font-weight:600;background:{BG[k]};color:{INK[k]};white-space:nowrap">{escape(t)}</span>')


def section(title, sub, inner):
    return (f'<tr><td style="padding:22px 0 6px"><div style="font-size:17px;font-weight:700;color:#141413">{title}</div>'
            f'<div style="font-size:12.5px;color:#8b8982;margin-top:2px">{sub}</div></td></tr>'
            f'<tr><td style="background:#fff;border:1px solid #e6e5df;border-radius:12px;padding:6px 14px">{inner}</td></tr>')


def table(head, rows, align=None):
    align = align or ["left"] * len(head)
    th = "".join(f'<th style="text-align:{a};font-size:11.5px;color:#8b8982;font-weight:500;padding:8px 6px;'
                 f'border-bottom:1px solid #e6e5df">{h}</th>' for h, a in zip(head, align))
    tr = "".join("<tr>" + "".join(f'<td style="text-align:{a};font-size:13px;color:#141413;padding:8px 6px;'
                                  f'border-bottom:1px solid #f0efea;vertical-align:top">{c}</td>'
                                  for c, a in zip(r, align)) + "</tr>" for r in rows)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{th}{tr}</table>'


# ───────── 판단 ─────────
def hotel_risk(D, o):
    """(등급, 문구) — 비율(하얏트÷대조군)이 오르거나 하얏트만 요금이 사라지면 위험"""
    s = [r for r in D["series"] if r["offset"] == o]
    if not s:
        return "muted", "데이터 없음"
    l = s[-1]
    if l["target_status"] == "no_rate" and l["control_n"] >= 2:
        return "crit", "하얏트만 요금 사라짐(매진 가능)"
    if l["target_status"] != "ok":
        return "muted", "하얏트 검색 미검출"
    z, basis = l["z_ratio"], "같은 요일"
    h = [r["ratio"] for r in s[:-1] if r["ratio"] is not None]
    if z is None and len(h) >= MIN_ALL:
        sd = statistics.pstdev(h)
        if sd:
            z, basis = (l["ratio"] - statistics.mean(h)) / sd, "임시·요일 무시"
    if z is None:
        return "muted", f"보류 {len(h)}/{MIN_ALL}일"
    zs = f"z {z:+.1f}, {basis}"
    if z >= D["config"]["z_alert"]:
        return "crit", f"위험 · {zs}"
    if z >= Z_WARN:
        return "warn", f"주의 · {zs}"
    return "good", f"정상 · {zs}"


RANK = {"crit": 3, "warn": 2, "good": 1, "muted": 0}


# ───────── 섹션 ─────────
def embassy_html(E):
    rows = []
    for s in E["sources"]:
        name = escape(s["name"])
        if s.get("error"):
            rows.append([f'{dot("muted")}{name}', chip("muted", "수집 실패"), ""])
            continue
        if s["level_norm"] is None:   # 단계 없는 공지 피드
            lt = s.get("latest")
            rows.append([f'{dot("muted")}{name}' + sub(escape(lt["title"][:70]) if lt else "한국 관련 공지 없음"),
                         chip("muted", "공지 피드"), ymd(lt["date"]) if lt else ""])
            continue
        k, ko = LV[s["level_norm"]]
        rows.append([f'{dot(k)}{name}' + sub(escape(s["level_text"] or "")), chip(k, f'{s["level_norm"]}단계 {ko}'),
                     ymd(s["updated"])])
    inner = table(["출처 · 원문 단계", "공통 단계", "갱신"], rows, ["left", "left", "right"])
    rec = E.get("recent") or []
    if rec:
        items = "".join(
            f'<tr><td style="padding:6px 0;font-size:12.5px;color:#8b8982;white-space:nowrap;vertical-align:top">{x["date"][5:10]}</td>'
            f'<td style="padding:6px 8px;vertical-align:top">{chip("crit" if x["severity"] == "critical" else "warn", "철수·출국" if x["severity"] == "critical" else "주의")}</td>'
            f'<td style="padding:6px 0;font-size:13px"><a href="{escape(x["url"] or "")}" style="color:#141413;text-decoration:none">{escape(x["title"])}</a>'
            f'<div style="font-size:11.5px;color:#8b8982">{escape(x["source"])}</div></td></tr>' for x in rec[:5])
        inner += (f'<div style="font-size:13px;font-weight:600;margin:14px 0 4px">최근 {E["recent_days"]}일 키워드 공지 '
                  f'<span style="font-weight:400;color:#8b8982">철수·출국 {E["counts"]["critical"]} · 주의 {E["counts"]["watch"]}</span></div>'
                  f'<table width="100%" cellpadding="0" cellspacing="0">{items}</table>')
    return inner


def hotel_html(D):
    rows = []
    for o in D["config"]["offsets"]:
        s = [r for r in D["series"] if r["offset"] == o]
        l = s[-1] if s else {}
        k, t = hotel_risk(D, o)
        rows.append([f"D+{o}", won(l.get("target_price")), won(l.get("control_median")),
                     f'{l["ratio"]:.2f}' if l.get("ratio") is not None else "—", chip(k, t)])
    return (table(["체크인", "하얏트", "대조군 중앙", "비율", "위험도"], rows, ["left", "right", "right", "right", "left"])
            + '<div style="font-size:12px;color:#8b8982;padding:10px 0 6px">비율 = 하얏트 ÷ 대조군(신라·반얀트리·포시즌스·JW메리어트) 중앙값. '
              '평소보다 <b style="color:#55534e">오르면</b> 위험 신호, 내려가는 건 위험 아님.</div>')


def news_html(N, today):
    l = N["latest"]
    late = lag(N, today)
    warn = (f'<div style="font-size:12.5px;color:{INK["warn"]};background:{BG["warn"]};border-radius:8px;padding:8px 10px;margin-top:10px">'
            f'GDELT 데이터가 {late}일째 갱신되지 않았습니다. 아래 수치는 {l["date"]} 기준입니다.</div>') if late > 3 else ""
    stat = (f'<b>{l["date"]}</b> 관련 기사 {l["count"]:,}건 · 만 건당 <b>{l["share"]:.1f}</b>'
            + (f' · 평소 {l["median"]:.1f} 대비 <b>{l["ratio"]:.1f}배</b> · z {l["z"]:+.1f}' if l.get("z") is not None
               else f' · 기준선 쌓는 중 ({l["base_n"]}/{N["config"]["min_base"]}일)'))
    arts = "".join(
        f'<tr><td style="padding:6px 0;font-size:13px;border-top:1px solid #f0efea">'
        f'<a href="{escape(a["url"] or "")}" style="color:#141413;text-decoration:none">{escape(a["title"])}</a>'
        f'<div style="font-size:11.5px;color:#8b8982">{escape(a.get("domain") or "")} · {escape(a.get("country") or "")}</div></td></tr>'
        for a in N.get("articles", [])[:5])
    return (warn + f'<div style="font-size:13px;color:#141413;padding:10px 0">{stat}</div>'
            + (f'<table width="100%" cellpadding="0" cellspacing="0">{arts}</table>' if arts else ""))


# ───────── 전체 ─────────
def render(today, alerts, fails, E, D, N):
    if alerts:
        vk, verdict, lead = "crit", f"경보 {len(alerts)}건", "아래 경보 내용을 먼저 확인하세요."
    elif fails:
        vk, verdict, lead = "warn", "점검 필요", "일부 수집이 실패했습니다. 나머지 지표는 정상 판단입니다."
    else:
        vk, verdict, lead = "good", "특이 동향 없음", "여행경보·대사관 공지·호텔 가격·언론 보도에서 평소와 다른 신호가 없습니다."

    # 요약 카드 3개
    cards = []
    if E:
        ok = [s for s in E["sources"] if not s.get("error")]
        lv = max([s["level_norm"] or 0 for s in ok], default=0)
        k = "crit" if E["alerts"] else LV.get(lv, ("muted",))[0]
        cards.append((k, "대사관·여행경보", f"최고 {lv}단계" if lv else "—",
                      f"{len(ok)}/{len(E['sources'])}개 출처 · 주의 공지 {E['counts']['watch']}건"))
    if D:
        w = max(((o,) + hotel_risk(D, o) for o in D["config"]["offsets"]), key=lambda x: RANK[x[1]])
        k = "crit" if D["alerts"] else w[1]
        cards.append((k, "남산 하얏트 가격", {"crit": "위험", "warn": "주의", "good": "정상", "muted": "판단 보류"}[k],
                      f"D+{w[0]} · {w[2]}" if k != "muted" else w[2]))
    if N:
        l = N["latest"]
        late = lag(N, today) > 3
        k = ("crit" if N["alerts"] else "muted" if late or l.get("z") is None else "warn" if N["watch"] else "good")
        cards.append((k, "세계 언론 동향", f'평소의 {l["ratio"]:.1f}배' if l.get("ratio") else f'만 건당 {l["share"]:.1f}',
                      f'{l["date"][5:]} 기준' + (" · 데이터 지연" if late else f' · z {l["z"]:+.1f}' if l.get("z") is not None else "")))
    card_td = "".join(
        f'<td width="{100 // max(len(cards), 1)}%" style="padding:4px;vertical-align:top">'
        f'<div style="background:{BG[k]};border-radius:10px;padding:12px">'
        f'<div style="font-size:11.5px;color:{INK[k]}">{dot(k)}{t}</div>'
        f'<div style="font-size:17px;font-weight:700;color:#141413;margin-top:4px">{escape(v)}</div>'
        f'<div style="font-size:11.5px;color:#55534e;margin-top:2px">{escape(sub)}</div></div></td>'
        for k, t, v, sub in cards)

    box = ""
    if alerts:
        box += (f'<div style="background:{BG["crit"]};border-left:4px solid {C["crit"]};border-radius:8px;padding:12px 14px;margin-top:14px">'
                f'<div style="font-weight:700;color:{INK["crit"]};margin-bottom:6px">🚨 경보</div>'
                + "".join(f'<div style="font-size:13px;color:#141413;margin:3px 0">• {escape(a)}</div>' for a in alerts) + "</div>")
    if fails:
        box += (f'<div style="background:{BG["warn"]};border-left:4px solid {C["warn"]};border-radius:8px;padding:12px 14px;margin-top:10px">'
                f'<div style="font-weight:700;color:{INK["warn"]};margin-bottom:6px">🔧 점검 필요</div>'
                + "".join(f'<div style="font-size:12.5px;color:#141413;margin:3px 0">• {escape(f)}</div>' for f in fails) + "</div>")

    body = ""
    if E:
        body += section("01 대사관·여행경보", "각국 정부가 자국민에게 내는 공식 경보 · 신뢰도 높음", embassy_html(E))
    if D:
        body += section("02 남산 그랜드 하얏트 가격", "공개 최저가를 대조군 호텔 4곳과 비교 · 신뢰도 낮음", hotel_html(D))
    if N:
        body += section("03 세계 언론 동향", "전체 기사 중 한반도 분쟁 기사 비율 (GDELT) · 신뢰도 중간", news_html(N, today))

    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f4f3ef">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f3ef"><tr><td align="center" style="padding:16px 8px">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;font-family:{FONT};color:#141413;word-break:break-word;overflow-wrap:anywhere;table-layout:fixed">
<tr><td style="font-size:12.5px;color:#8b8982;padding-bottom:8px">전쟁 위험 지표 · {today}</td></tr>
<tr><td style="background:#fff;border:1px solid #e6e5df;border-left:5px solid {C[vk]};border-radius:14px;padding:18px 18px 14px">
  <div style="font-size:24px;font-weight:800;color:{INK[vk]}">{dot(vk)}{verdict}</div>
  <div style="font-size:13.5px;color:#55534e;margin-top:4px">{lead}</div>
  {box}
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px"><tr>{card_td}</tr></table>
</td></tr>
{body}
<tr><td style="padding:22px 0 8px" align="center">
  <a href="{SITE}" style="display:inline-block;background:#141413;color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:11px 22px;border-radius:10px">사이트에서 그래프 보기</a>
</td></tr>
<tr><td style="font-size:11.5px;color:#8b8982;padding:10px 0;line-height:1.6" align="center">
  공개 정보 기반 참고용 지표입니다. 위급 시 외교부 해외안전여행(0404.go.kr)과 국민재난안전포털을 우선 확인하세요.
</td></tr>
</table></td></tr></table></body></html>"""


def build(today, alerts, fails):
    return render(today, alerts, fails, load("data/embassy.json"), load("data/metrics.json"), load("data/news.json"))
