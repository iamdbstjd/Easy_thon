"""계약 일정 체크리스트 → iCalendar(.ics) 파일.

- 잔금일·입주일 항목(날짜가 있는 것)만 종일 일정으로 만든다.
- 일정이 하나도 없어도 RFC 5545상 올바른 파일이 되도록(구성요소 1개 이상) Asia/Seoul VTIMEZONE을 항상 넣는다.
- 알림은 하루 전 09:00이다. 종일 일정은 그날 0시에 시작하므로 15시간 전(-PT15H)이다.
- 줄 끝은 CRLF이고, 75바이트를 넘는 줄은 UTF-8 글자를 자르지 않고 접는다.
"""

from __future__ import annotations

import datetime as dt
import hashlib

from app.schemas import IcsRequest

FILENAME = "bojeunggeum-checklist.ics"
MEDIA_TYPE = "text/calendar"
PRODID = "-//Bojeunggeum Jikimi//Checklist 0.1//KO"
CALENDAR_NAME = "보증금 지킴이 계약 일정"
SUMMARY_PREFIX = "[보증금 지킴이]"
ALARM_TRIGGER = "-PT15H"
EVENT_WHENS = ("잔금일", "입주일")  # 캘린더에 넣는 체크리스트 시점
TIMEZONE_LINES = [  # 한국은 서머타임이 없어 STANDARD 하나로 충분하다
    "BEGIN:VTIMEZONE",
    "TZID:Asia/Seoul",
    "X-LIC-LOCATION:Asia/Seoul",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0900",
    "TZOFFSETTO:+0900",
    "TZNAME:KST",
    "DTSTART:19700101T000000",
    "END:STANDARD",
    "END:VTIMEZONE",
]
UID_DOMAIN = "bojeunggeum-jikimi.local"

CRLF = "\r\n"
MAX_LINE_OCTETS = 75


def escape_text(value: str) -> str:
    """TEXT 값 이스케이프: 역슬래시, 쉼표, 세미콜론, 줄바꿈."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def fold_line(line: str) -> str:
    """75바이트를 넘는 줄을 접는다. 이어지는 줄은 공백 하나로 시작한다 (공백도 75바이트에 포함)."""
    if len(line.encode("utf-8")) <= MAX_LINE_OCTETS:
        return line
    parts: list[str] = []
    current, size = "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > MAX_LINE_OCTETS:
            parts.append(current)
            current, size = " ", 1
        current += ch
        size += n
    parts.append(current)
    return CRLF.join(parts)


def _uid(index: int, when: str, date: dt.date, title: str, address: str | None) -> str:
    # 같은 입력이면 같은 UID → 다시 가져와도 일정이 중복되지 않는다.
    key = f"{index}|{when}|{date.isoformat()}|{title}|{address or ''}"
    return f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}@{UID_DOMAIN}"


def build_ics(req: IcsRequest, *, now: dt.datetime | None = None) -> str:
    """체크리스트의 잔금일·입주일 일정을 .ics 문자열로 만든다. 날짜가 없거나 다른 시점인 항목은 건너뛴다."""
    stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(CALENDAR_NAME)}",
        *TIMEZONE_LINES,
    ]
    for index, item in enumerate(req.checklist):
        if item.date is None or item.when.strip() not in EVENT_WHENS:
            continue
        summary = escape_text(f"{SUMMARY_PREFIX} {item.when}: {item.title}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_uid(index, item.when, item.date, item.title, req.address)}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{item.date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(item.date + dt.timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{summary}",
        ]
        if req.address:
            lines.append(f"DESCRIPTION:{escape_text('주소: ' + req.address)}")
        lines += [
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{summary}",
            f"TRIGGER:{ALARM_TRIGGER}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return CRLF.join(fold_line(line) for line in lines) + CRLF
