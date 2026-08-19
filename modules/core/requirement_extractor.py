"""
Экстрактор требований: превращает сырой текст документации закупки
в структурированный TenderRequirements
======================================================================

Модель-агностично: сюда подставляется любая функция вызова LLM
(YandexGPT, GigaChat, локальная модель) — она передаётся параметром
call_llm, чтобы не завязываться на конкретного провайдера прямо сейчас.

Пока нет ни токена ЕИС, ни реальных документов клиента, здесь есть
demo-режим на моковом LLM: он не "понимает" текст, а просто возвращает
заранее заданный ответ — это нужно только чтобы проверить, что весь
конвейер (текст -> промпт -> JSON -> TenderRequirements -> линтер)
технически работает и не падает. Как только появится реальный документ,
mock_llm меняется на настоящий вызов YandexGPT/GigaChat API — остальной
код менять не придётся.
"""

import json
from datetime import date, datetime
from typing import Callable, Optional

from modules.core.tender_models import TenderRequirements

# ---------------- Промпт для реальной модели ----------------

EXTRACTION_PROMPT_TEMPLATE = """Ты — ассистент по разбору документации государственных закупок (44-ФЗ).
Из текста ниже извлеки только то, что ЯВНО указано в документе. Если чего-то нет
или неоднозначно — не придумывай, помечай поле как null и добавляй его имя
в low_confidence_fields.

Верни ТОЛЬКО валидный JSON со следующими полями (без комментариев и пояснений):
{{
  "application_security_amount": число или null (обеспечение заявки, руб.),
  "contract_security_amount": число или null (обеспечение контракта, руб.),
  "bank_guarantee_allowed": true/false (допускается ли банковская гарантия),
  "antidemping_threshold_percent": число или null (порог антидемпинга по ст. 37 44-ФЗ, %),
  "required_documents": [список строк — документы, требуемые именно в этой закупке],
  "requires_sme_status": true/false (закупка только для СМП/СОНКО),
  "requires_license": строка или null (какая лицензия нужна, если требуется),
  "requires_experience": true/false (требуется ли опыт аналогичных поставок),
  "delivery_deadline": "YYYY-MM-DD" или null,
  "warranty_period_months": число или null,
  "production_lead_time_days": число или null (сколько дней нужно на изготовление номенклатуры —
      грубая оценка по описанию: серийная стандартная продукция быстрее, нетиповая/по чертежам
      заказчика — дольше; если оценить невозможно, ставь null и добавляй в low_confidence_fields),
  "low_confidence_fields": [список имён полей выше, которые извлечены неуверенно]
}}

Реестровый номер закупки: {reestr_number}

Текст документации:
---
{document_text}
---
"""


def build_extraction_prompt(reestr_number: str, document_text: str) -> str:
    return EXTRACTION_PROMPT_TEMPLATE.format(reestr_number=reestr_number, document_text=document_text)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_llm_response(reestr_number: str, raw_json: str) -> TenderRequirements:
    """Превращает JSON-ответ модели в TenderRequirements. Кидает исключение,
    если модель вернула не-JSON — это осознанно: молча проглатывать ошибку
    разбора хуже, чем упасть и заметить, что промпт/модель дали сбой."""
    data = json.loads(raw_json)
    return TenderRequirements(
        reestr_number=reestr_number,
        application_security_amount=data.get("application_security_amount"),
        contract_security_amount=data.get("contract_security_amount"),
        bank_guarantee_allowed=data.get("bank_guarantee_allowed", True),
        antidemping_threshold_percent=data.get("antidemping_threshold_percent"),
        required_documents=data.get("required_documents", []) or [],
        requires_sme_status=data.get("requires_sme_status", False),
        requires_license=data.get("requires_license"),
        requires_experience=data.get("requires_experience", False),
        delivery_deadline=_parse_date(data.get("delivery_deadline")),
        warranty_period_months=data.get("warranty_period_months"),
        production_lead_time_days=data.get("production_lead_time_days"),
        low_confidence_fields=data.get("low_confidence_fields", []) or [],
    )


def extract_requirements(
    reestr_number: str,
    document_text: str,
    call_llm: Callable[[str], str],
) -> TenderRequirements:
    """call_llm — функция, которая принимает промпт (строку) и возвращает
    ответ модели (строку с JSON). Сюда подставляется реальный клиент
    YandexGPT/GigaChat, когда он появится."""
    prompt = build_extraction_prompt(reestr_number, document_text)
    raw_response = call_llm(prompt)
    return parse_llm_response(reestr_number, raw_response)


# ---------------- Выжимка для быстрого чтения + ссылка на извещение ----------------

def build_digest(reqs: TenderRequirements) -> str:
    """Короткая текстовая выжимка вместо перечитывания всех полей по
    отдельности — специально проверяет, хватает ли времени на изготовление
    номенклатуры до срока поставки (production_lead_time_days против
    delivery_deadline), если оба поля известны."""
    lines = [f"Закупка № {reqs.reestr_number}"]

    if reqs.application_security_amount is not None:
        lines.append(f"Обеспечение заявки: {reqs.application_security_amount:,.0f} ₽".replace(",", " "))
    if reqs.contract_security_amount is not None:
        lines.append(f"Обеспечение контракта: {reqs.contract_security_amount:,.0f} ₽".replace(",", " "))
    if reqs.delivery_deadline is not None:
        lines.append(f"Срок поставки: {reqs.delivery_deadline.strftime('%d.%m.%Y')}")
    if reqs.production_lead_time_days is not None:
        note = ""
        if reqs.delivery_deadline is not None:
            days_available = (reqs.delivery_deadline - date.today()).days
            if days_available < reqs.production_lead_time_days:
                note = (
                    f" — ВНИМАНИЕ: до срока поставки {days_available} дн., а на "
                    f"изготовление нужно {reqs.production_lead_time_days} дн., может не хватить времени"
                )
        lines.append(f"Оценка срока изготовления: {reqs.production_lead_time_days} дн.{note}")
    if reqs.warranty_period_months is not None:
        lines.append(f"Гарантия: {reqs.warranty_period_months} мес.")
    if reqs.requires_sme_status:
        lines.append("Только для СМП/СОНКО")
    if reqs.required_documents:
        lines.append(f"Требуемые документы: {', '.join(reqs.required_documents)}")
    if reqs.low_confidence_fields:
        lines.append(f"⚠ Проверить вручную: {', '.join(reqs.low_confidence_fields)}")

    return "\n".join(lines)


def build_eis_notice_url(reestr_number: str) -> str:
    """Прямая ссылка на извещение в ЕИС по реестровому номеру — построена
    по стандартному публичному URL-шаблону zakupki.gov.ru (не проверялась
    вживую в этой среде, как и eis_client.py, — сеть ЕИС недоступна)."""
    return f"https://zakupki.gov.ru/epz/order/notice/notice44/view/common-info.html?regNumber={reestr_number.strip()}"


# ---------------- Демонстрация конвейера на моковом LLM ----------------

def _mock_llm(prompt: str) -> str:
    """ВНИМАНИЕ: это не реальное распознавание, а заглушка для проверки,
    что конвейер технически не падает. Ответ ниже — заранее заданный,
    к тексту в промпте он не приглядывается."""
    return json.dumps({
        "application_security_amount": 45000,
        "contract_security_amount": 180000,
        "bank_guarantee_allowed": True,
        "antidemping_threshold_percent": 25,
        "required_documents": ["Выписка из ЕГРЮЛ", "Декларация соответствия требованиям ст. 31 44-ФЗ"],
        "requires_sme_status": True,
        "requires_license": None,
        "requires_experience": False,
        "delivery_deadline": "2026-10-01",
        "warranty_period_months": 12,
        "production_lead_time_days": 21,
        "low_confidence_fields": ["antidemping_threshold_percent", "production_lead_time_days"],
    }, ensure_ascii=False)


if __name__ == "__main__":
    example_text = (
        "ДЕМО-ТЕКСТ (не настоящая документация закупки, только для проверки конвейера). "
        "Извещение о проведении электронного аукциона. Обеспечение заявки — 45 000 руб. "
        "Обеспечение исполнения контракта — 180 000 руб. Гарантийный срок — 12 месяцев. "
        "Срок поставки — до 01.10.2026. Участие только для субъектов МСП."
    )

    requirements = extract_requirements(
        reestr_number="ДЕМО-0000000000000000000",
        document_text=example_text,
        call_llm=_mock_llm,
    )

    print("Извлечённые требования (мок-режим, не для реального использования):")
    print(requirements)
    if requirements.low_confidence_fields:
        print(f"\nПоля, извлечённые неуверенно (нужна ручная проверка): {requirements.low_confidence_fields}")

    print("\n=== Выжимка ===")
    digest = build_digest(requirements)
    print(digest)
    assert "Закупка №" in digest and "Оценка срока изготовления" in digest

    url = build_eis_notice_url(requirements.reestr_number)
    print(f"\nСсылка на извещение: {url}")
    assert url.startswith("https://zakupki.gov.ru/") and requirements.reestr_number in url

    print("\nПроверка пройдена: выжимка и ссылка строятся корректно.")
