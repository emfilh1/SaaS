"""
Клиент к Bitrix24 REST API через входящий вебхук
====================================================

Что это: создаёт задачи и/или события в календаре Bitrix24 на основе
дедлайнов из post_contract_tracker.py — чтобы после победы в тендере
сроки поставки, закрывающих документов, гарантии и обеспечения сами
появлялись у ответственного сотрудника, а не жили только в этом
приложении.

Как получить вебхук (5 минут, без разработчика):
1. В Bitrix24: Приложения -> Разработчикам -> Другое -> Входящий вебхук.
2. Выдать права (scope) минимум: "Задачи" (task) и "Календарь" (calendar).
3. Bitrix24 покажет готовую ссылку вида
   https://ваш-портал.bitrix24.ru/rest/1/xxxxxxxxxxxxxxxxxxxx/
   — это и есть BASE_URL ниже (со слэшем на конце или без, неважно).
4. RESPONSIBLE_ID — числовой ID сотрудника в Bitrix24 (его можно
   посмотреть в профиле пользователя, в адресной строке).

Не проверялось вживую (нет доступа к реальному порталу Bitrix24 в этой
среде) — написано строго по официальной документации apidocs.bitrix24.com,
проверенной веб-поиском в августе 2026 (ссылки внизу файла). Главный риск
при первом реальном запуске — единственный: у ответственного сотрудника
должен существовать хотя бы один раздел календаря (calendar.section.get);
если календарь Bitrix24 никогда не открывался, раздела может не быть —
тогда create_calendar_event() кинет понятную ошибку с этой же подсказкой.
"""

from datetime import date, datetime
from typing import Optional

import requests

from modules.tracking.post_contract_tracker import TrackedEvent, СТАТУС_ВЫПОЛНЕНО


def _call(webhook_base_url: str, method: str, payload: dict) -> dict:
    # защита от частой ошибки копирования: если вставили ссылку с уже
    # приклеенным именем метода (например, скопировали из адресной строки
    # после тестового запроса) — отрезаем лишний хвост, а не молча ломаем URL
    base = webhook_base_url.rstrip("/")
    if base.endswith(".json"):
        base = base.rsplit("/", 1)[0]
    url = base + f"/{method}.json"
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(
            f"Bitrix24 вернул ошибку ({data['error']}): {data.get('error_description', 'без описания')}"
        )
    return data["result"]


def create_task(
    webhook_base_url: str,
    title: str,
    responsible_id: int,
    description: str = "",
    deadline: Optional[date] = None,
) -> int:
    fields = {"TITLE": title, "RESPONSIBLE_ID": responsible_id, "DESCRIPTION": description}
    if deadline:
        fields["DEADLINE"] = datetime.combine(deadline, datetime.min.time()).strftime("%Y-%m-%dT%H:%M:%S")
    result = _call(webhook_base_url, "tasks.task.add", {"fields": fields})
    return int(result["task"]["id"])


def get_default_calendar_section(webhook_base_url: str, owner_id: int) -> int:
    """Возвращает ID первого доступного раздела личного календаря сотрудника —
    его Bitrix24 требует явно указывать в calendar.event.add."""
    result = _call(webhook_base_url, "calendar.section.get", {"type": "user", "ownerId": owner_id})
    if not result:
        raise RuntimeError(
            "У сотрудника нет ни одного раздела календаря в Bitrix24 — "
            "нужно хотя бы раз открыть 'Календарь' в интерфейсе Bitrix24, "
            "чтобы раздел по умолчанию создался."
        )
    return int(result[0]["ID"])


def create_calendar_event(
    webhook_base_url: str,
    owner_id: int,
    name: str,
    event_date: date,
    description: str = "",
    section_id: Optional[int] = None,
    tz_offset: str = "+03:00",
) -> int:
    if section_id is None:
        section_id = get_default_calendar_section(webhook_base_url, owner_id)

    start = f"{event_date.isoformat()}T09:00:00{tz_offset}"
    end = f"{event_date.isoformat()}T10:00:00{tz_offset}"
    result = _call(webhook_base_url, "calendar.event.add", {
        "type": "user",
        "ownerId": owner_id,
        "section": section_id,
        "name": name,
        "from": start,
        "to": end,
        "description": description,
        "remind": [{"type": "min", "count": 60 * 24}],  # напомнить за сутки
    })
    # calendar.event.add обычно возвращает ID события напрямую; на случай,
    # если портал вернёт его завёрнутым в объект — обрабатываем оба варианта
    if isinstance(result, dict):
        return int(result.get("id") or result.get("ID"))
    return int(result)


def push_tracked_events(
    webhook_base_url: str,
    responsible_id: int,
    events: list[TrackedEvent],
    contract_label: str,
    create_tasks: bool = True,
    create_calendar_events: bool = True,
) -> list[dict]:
    """Прогоняет список TrackedEvent (post_contract_tracker.get_tracked_events)
    через Bitrix24: на каждый ещё не выполненный дедлайн с известной датой —
    задача и/или событие календаря. Не останавливается на первой ошибке —
    копит результат по каждому событию, чтобы одна проблема (например,
    просроченный вебхук) не помешала создать остальное."""
    results = []
    for event in events:
        if event.due_date is None or event.status == СТАТУС_ВЫПОЛНЕНО:
            continue

        title = f"[{contract_label}] {event.description}"
        entry = {"event": event.description, "task_id": None, "calendar_event_id": None, "errors": []}

        if create_tasks:
            try:
                entry["task_id"] = create_task(
                    webhook_base_url, title, responsible_id,
                    description=event.recommendation, deadline=event.due_date,
                )
            except Exception as e:
                entry["errors"].append(f"Задача: {e}")

        if create_calendar_events:
            try:
                entry["calendar_event_id"] = create_calendar_event(
                    webhook_base_url, responsible_id, title, event.due_date,
                    description=event.recommendation,
                )
            except Exception as e:
                entry["errors"].append(f"Календарь: {e}")

        results.append(entry)
    return results


# ----------------------------------------------- дайджест для руководителя

def build_executive_digest_text(
    reestr_number: str,
    subject: str,
    nmck: Optional[float] = None,
    proposed_price: Optional[float] = None,
    contract_draft_summary: str = "",
) -> str:
    """Чистая функция без сети — собирает текст дайджеста, чтобы его
    можно было проверить и показать в интерфейсе до того, как реально
    слать в Bitrix24 (push_executive_digest ниже только оборачивает её
    в create_task)."""
    lines = [f"Закупка № {reestr_number}", f"Предмет: {subject}"]
    if nmck is not None:
        lines.append(f"НМЦК: {nmck:,.0f} ₽".replace(",", " "))
    if proposed_price is not None:
        lines.append(f"Предложенная цена: {proposed_price:,.0f} ₽".replace(",", " "))
    if contract_draft_summary:
        lines.append(f"Проект контракта/ТЗ: {contract_draft_summary}")
    return "\n".join(lines)


def push_executive_digest(
    webhook_base_url: str,
    ceo_id: int,
    reestr_number: str,
    subject: str,
    nmck: Optional[float] = None,
    proposed_price: Optional[float] = None,
    contract_draft_summary: str = "",
    deadline: Optional[date] = None,
) -> int:
    """Создаёт в Bitrix24 задачу для руководителя с ключевыми цифрами по
    тендеру, чтобы решение по цене и участию не приходилось искать по
    вкладкам приложения. Естественная точка вызова — переход карточки
    тендера (tender_pipeline.py) на этап "Принятие решения по цене и
    участию"."""
    description = build_executive_digest_text(reestr_number, subject, nmck, proposed_price, contract_draft_summary)
    title = f"Решение по тендеру № {reestr_number}"
    return create_task(webhook_base_url, title, ceo_id, description=description, deadline=deadline)


if __name__ == "__main__":
    import os

    print("=== Оффлайн-проверка текста дайджеста (без сети) ===")
    digest_text = build_executive_digest_text(
        "ДЕМО-0000000000000000001", "Поставка металлопроката листового",
        nmck=2_400_000, proposed_price=2_150_000,
        contract_draft_summary="Проект контракта получен, срок поставки 01.10.2026",
    )
    print(digest_text)
    assert "НМЦК" in digest_text and "2 400 000" in digest_text
    print("\nПроверка текста дайджеста пройдена.")

    webhook = os.environ.get("BITRIX24_WEBHOOK_URL")
    responsible = os.environ.get("BITRIX24_RESPONSIBLE_ID")
    if not webhook or not responsible:
        print("\nЗадай переменные окружения BITRIX24_WEBHOOK_URL и BITRIX24_RESPONSIBLE_ID, чтобы проверить сетевые вызовы вживую.")
        raise SystemExit(0)

    task_id = create_task(
        webhook, "Тестовая задача из тендер-помощника", int(responsible),
        description="Если задача появилась в Bitrix24 — вебхук настроен верно.",
        deadline=date.today(),
    )
    print(f"Создана задача #{task_id}")

# Источники (проверено веб-поиском и по официальной документации, август 2026):
# - https://apidocs.bitrix24.com/local-integrations/local-webhooks.html (структура вебхука)
# - https://apidocs.bitrix24.com/api-reference/tasks/tasks-task-add.html (поля задачи, формат DEADLINE)
# - https://apidocs.bitrix24.com/api-reference/calendar/calendar-event/calendar-event-add.html (поля события, формат from/to)
# - https://apidocs.bitrix24.com/api-reference/calendar/calendar-section-get.html (получение ID раздела календаря)
