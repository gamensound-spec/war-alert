"""
일간 통합 리포트: 대사관·여행경보 + 호텔 지표 + 세계 언론 동향을 한 통의 Gmail로 보낸다.
한 모듈이 실패해도 나머지는 그대로 보내고, 실패 사실을 본문에 적는다.
"""
import re
import smtplib
import datetime as dt
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import hotel_monitor
import embassy_monitor
import news_monitor
import market_monitor
import attention_monitor
import air_monitor
import mail_report


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
    parts = [("대사관·여행경보", embassy_monitor.run), ("남산 하얏트 가격", hotel),
             ("세계 언론 동향", news_monitor.run), ("시장 스트레스", market_monitor.run),
             ("대중 관심도", attention_monitor.run), ("항공 교통", air_monitor.run)]
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
        send(subject, body, mail_report.build(today.isoformat(), alerts, fails))
    return subject, body


def send(subject, text, html):
    """HTML 메일. 텍스트 본문을 함께 넣어 HTML을 못 여는 앱에서도 읽히게 한다"""
    h = hotel_monitor
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, h.GMAIL_USER, h.MAIL_TO
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(h.GMAIL_USER, h.GMAIL_APP_PASSWORD)
        s.send_message(msg)


if __name__ == "__main__":
    print(*run(), sep="\n")
