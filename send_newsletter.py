"""뉴스레터 발송 — 매일 아침 7시(KST) Actions에서 실행.

배포된 newsletter.html(매시간 최신 브리핑으로 재생성됨)을 그대로 가져와
Gmail SMTP로 구독자에게 BCC 발송한다. 구독자 명단은 공개 저장소에 둘 수
없으므로(개인정보) GitHub Secret `NEWSLETTER_RECIPIENTS`에 보관한다.

필요 시크릿:
  GMAIL_USER            발신 Gmail 주소
  GMAIL_APP_PASSWORD    Gmail 앱 비밀번호 (2단계 인증 → 앱 비밀번호 생성)
  NEWSLETTER_RECIPIENTS 수신자 목록 (쉼표·공백·줄바꿈 구분)

시크릿이 없으면 실패 대신 안내만 출력하고 정상 종료한다 — 프로비저닝
전에도 워크플로가 빨간불이 되지 않게.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

KST = timezone(timedelta(hours=9))
NEWSLETTER_URL = "https://goreunnews.cloud/newsletter.html"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_recipients(raw: str) -> list[str]:
    seen: dict[str, None] = {}
    for token in re.split(r"[,\s;]+", raw):
        addr = token.strip().lower()
        if addr and _EMAIL_RE.match(addr):
            seen.setdefault(addr, None)
    return list(seen)


def fetch_html(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def main() -> int:
    user = os.environ.get("GMAIL_USER", "").strip()
    app_pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    recipients = parse_recipients(os.environ.get("NEWSLETTER_RECIPIENTS", ""))

    if not (user and app_pw):
        print("GMAIL_USER/GMAIL_APP_PASSWORD 시크릿 미설정 — 발송 건너뜀 (안내: README '뉴스레터 발송' 절)")
        return 0
    if not recipients:
        print("NEWSLETTER_RECIPIENTS 비어 있음 — 발송 건너뜀")
        return 0

    html = fetch_html(NEWSLETTER_URL)
    now = datetime.now(KST)
    subject = f"☀️ 고른뉴스 아침 브리핑 — {now.month}월 {now.day}일"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("고른뉴스", user))
    msg["To"] = user  # 구독자는 전원 BCC — 서로의 주소가 노출되지 않게
    msg["List-Unsubscribe"] = f"<mailto:{user}?subject=%EC%88%98%EC%8B%A0%EA%B1%B0%EB%B6%80>"
    msg.attach(MIMEText(
        f"고른뉴스 아침 브리핑입니다. HTML을 지원하는 메일 앱에서 열어주세요.\n"
        f"웹에서 보기: {NEWSLETTER_URL}\n수신거부: 이 메일에 '수신거부'로 회신", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
        smtp.login(user, app_pw)
        smtp.send_message(msg, from_addr=user, to_addrs=[user] + recipients)
    print(f"발송 완료: 구독자 {len(recipients)}명 (BCC) · '{subject}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
