"""
Экспорт дедлайнов трекера в .ics (iCalendar, RFC 5545)
==========================================================

Не требует ни интернета, ни аккаунта, ни API — просто текстовый файл,
который открывается и импортируется в любой календарь (Google, Apple,
Outlook, Яндекс.Календарь) на телефоне или компьютере. Самый надёжный
запасной вариант, если Bitrix24 (bitrix24_client.py) недоступен или
не настроен: события всё равно попадут в личный календарь и будут
напоминать за сутки.
"""

from datetime import datetime, timezone
import uuid

from modules.tracking.post_contract_tracker import TrackedEvent

FOLD_LIMIT = 35  # с запасом ниже лимита в 75 октетов из RFC 5545 даже для кириллицы (2 байта/символ)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 требует 'сворачивать' длинные строки: перенос строки (CRLF)
    + один пробел в начале продолжения. Заново собираем всю логику простым
    посимвольным разбиением — без него часть календарных клиентов обрежет
    длинное описание или откажется парсить файл."""
    if len(line) <= FOLD_LIMIT:
        return line
    parts = []
    while len(line) > FOLD_LIMIT:
        parts.append(line[:FOLD_LIMIT])
        line = " " + line[FOLD_LIMIT:]
    parts.append(line)
    return "\r\n".join(parts)


def build_ics(events: list[TrackedEvent], contract_label: str) -> str:
    """contract_label — то, что будет в начале названия каждого события
    (например, 'Реестровый номер / заказчик'), чтобы в общем календаре
    было понятно, к какому контракту относится напоминание."""
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Тендер-помощник//RU", "CALSCALE:GREGORIAN"]

    for event in events:
        if event.due_date is None:
            continue
        uid = f"{uuid.uuid4()}@tender-pomoshnik"
        summary = _escape(f"[{contract_label}] {event.description}")
        description = _escape(event.recommendation)
        dtstart = event.due_date.strftime("%Y%m%d")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_utc}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            _fold(f"SUMMARY:{summary}"),
            _fold(f"DESCRIPTION:{description}"),
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:Напоминание",
            "TRIGGER:-P1D",
            "END:VALARM",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


if __name__ == "__main__":
    from datetime import date, timedelta
    from modules.tracking.post_contract_tracker import build_contract_from_requirements, get_tracked_events, ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ

    today = date.today()
    contract = build_contract_from_requirements(
        reestr_number="ДЕМО-0000000000000000000",
        customer_name="ДЕМО Заказчик (пример)",
        contract_price=1_200_000,
        signing_date=today - timedelta(days=40),
        delivery_deadline=today - timedelta(days=10),
        warranty_period_months=12,
        security_amount=180_000,
        security_type=ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ,
        security_expiry_date=today + timedelta(days=5),
    )
    ics_text = build_ics(get_tracked_events(contract, today=today), "ДЕМО-0000000000000000000")
    print(ics_text)
    assert "BEGIN:VCALENDAR" in ics_text and "END:VCALENDAR" in ics_text
    print("Проверка пройдена: .ics собирается без ошибок.")
