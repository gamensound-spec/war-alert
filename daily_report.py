"""
일간 통합 리포트: 호텔 지표 + 대사관·여행경보를 한 통의 Gmail로 보낸다.
한 모듈이 실패해도 나머지는 그대로 보내고, 실패 사실을 본문에 적는다.
"""
import re
import datetime as dt
import traceback

import hotel_monitor
import embassy_monitor


def section(title, fn):
    """(alerts, 실패 메시지 또는 None, 본문)"""
    try:
        alerts, lines = fn()
        return alerts, None, f"■ {title}\n" + "\n".join(lines)
    except Exception:
        err = traceback.format_exc(limit=2).strip().splitlines()[-1]
        err = re.sub(r"(api_key=)[^&\s]+", r"\1***", err)   # SerpApi 오류 URL에 키가 들어 있음
        return [], f"{title} 모듈 실행 실패: {err}", f"■ {title}\n실행 실패: {err}"


def hotel():
    _, body = hotel_monitor.run(mail=False)
    head, _, rest = body.partition("\n\n")
    alerts = head.splitlines()[1:] if head.startswith("🚨") else []
    return alerts, rest.splitlines()


def run(mail=True):
    today = dt.datetime.now(hotel_monitor.KST).date()
    parts = [("대사관·여행경보", embassy_monitor.run), ("남산 하얏트 가격", hotel)]
    alerts, fails, bodies = [], [], []
    for title, fn in parts:
        a, f, b = section(title, fn)
        alerts += [f"[{title}] {x}" for x in a]
        fails += [f] if f else []
        bodies.append(b)
    head = "🚨 경보\n" + "\n".join(alerts) + "\n\n" if alerts else "이상 없음\n\n"
    if fails:
        head += "🔧 점검 필요\n" + "\n".join(fails) + "\n\n"
    body = head + "\n\n".join(bodies)
    tag = "경보" if alerts else "점검" if fails else "일간"
    subject = f"[{tag}] 전쟁 위험 지표 {today}"
    if mail:
        hotel_monitor.send_mail(subject, body, hotel_monitor.CHART_FILE)
    return subject, body


if __name__ == "__main__":
    print(*run(), sep="\n")
