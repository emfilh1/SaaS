"""
Линтер заявки на участие в тендере (44-ФЗ)
=============================================

Что это: чек-лист самых частых формальных причин отклонения заявки
поставщика по 44-ФЗ. Это не весь возможный набор требований (они всегда
уникальны для конкретной закупки — их достаёт модуль "Экстрактор
требований" из документации), а базовый, общий для всех тендеров слой
проверок, который можно прогонять всегда, независимо от конкретной
закупки.

Не требует ни токена ЕИС, ни реальных документов клиента — источник это
общедоступная практика и разборы юристов по 44-ФЗ (см. источники внизу
файла). Как только появятся токен и реальная документация, эти правила
дополнятся специфичными для конкретного тендера условиями, которые
достанет "Экстрактор требований".

Как пользоваться сейчас (до появления интерфейса): заполнить словарь
ANSWERS вручную по конкретной заявке и запустить файл — на выходе
список сработавших рисков с рекомендацией.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class ChecklistItem:
    id: str
    stage: str  # "Часть 1", "Часть 2", "Обеспечение", "Подписание"
    risk: str
    check: Callable[[dict], bool]  # возвращает True, если риск сработал
    recommendation: str


CHECKLIST: list[ChecklistItem] = [
    ChecklistItem(
        id="нет_документов_часть1",
        stage="Часть 1",
        risk="Не предоставлены обязательные сведения/документы в первой части заявки",
        check=lambda a: a.get("part1_all_docs_provided") is False,
        recommendation="Сверить состав первой части с перечнем в извещении/документации закупки построчно.",
    ),
    ChecklistItem(
        id="не_обезличена_часть1",
        stage="Часть 1",
        risk="В первой части случайно указаны сведения о поставщике или цена — заявка должна быть обезличена на этом этапе",
        check=lambda a: a.get("part1_contains_supplier_info_or_price") is True,
        recommendation="Убрать из первой части любые упоминания названия компании, ИНН, цены — они допустимы только во второй части.",
    ),
    ChecklistItem(
        id="недостоверные_сведения",
        stage="Часть 1",
        risk="В заявке есть недостоверные сведения",
        check=lambda a: a.get("info_verified_against_originals") is False,
        recommendation="Сверить каждое утверждение в заявке (характеристики товара, сроки, показатели) с оригиналами документов и сертификатами.",
    ),
    ChecklistItem(
        id="обеспечение_не_оплачено",
        stage="Обеспечение",
        risk="Обеспечение заявки не перечислено или перечислено не в полном объёме",
        check=lambda a: a.get("security_amount_paid", 0) < a.get("security_amount_required", 0),
        recommendation="Проверить, что сумма обеспечения на спецсчёте равна или больше требуемой в извещении, и оплата прошла до окончания срока подачи.",
    ),
    ChecklistItem(
        id="гарантия_не_соответствует",
        stage="Обеспечение",
        risk="Независимая (банковская) гарантия не соответствует требованиям 44-ФЗ",
        check=lambda a: a.get("using_bank_guarantee") is True and a.get("guarantee_matches_44fz_requirements") is False,
        recommendation="Сверить гарантию со ст. 45 44-ФЗ: срок действия, сумма, безотзывность, перечень оснований для выплаты.",
    ),
    ChecklistItem(
        id="неполный_пакет_часть2",
        stage="Часть 2",
        risk="Неполный пакет документов во второй части заявки",
        check=lambda a: a.get("part2_all_docs_provided") is False,
        recommendation="Сверить состав второй части с документацией закупки — каждый документ, указанный там, должен быть приложен.",
    ),
    ChecklistItem(
        id="егрюл_устарела",
        stage="Часть 2",
        risk="Выписка из ЕГРЮЛ/ЕГРИП старше срока, разрешённого документацией (обычно не старше 6 месяцев)",
        check=lambda a: a.get("egrul_age_months", 0) > a.get("egrul_max_age_months_allowed", 6),
        recommendation="Запросить свежую выписку из ЕГРЮЛ непосредственно перед подачей заявки.",
    ),
    ChecklistItem(
        id="полномочия_просрочены",
        stage="Подписание",
        risk="Просрочены документы, подтверждающие полномочия лица, подписывающего заявку (доверенность, приказ)",
        check=lambda a: a.get("signatory_authority_valid") is False,
        recommendation="Проверить срок действия доверенности/приказа на лицо, подписывающее заявку электронной подписью, до подачи.",
    ),
]


def run_checklist(answers: dict) -> list[dict]:
    """Прогоняет ANSWERS через все правила и возвращает список сработавших рисков."""
    triggered = []
    for item in CHECKLIST:
        try:
            if item.check(answers):
                triggered.append({
                    "id": item.id,
                    "stage": item.stage,
                    "risk": item.risk,
                    "recommendation": item.recommendation,
                })
        except Exception:
            # если нужных полей нет в answers — считаем, что проверка не пройдена, и просим уточнить
            triggered.append({
                "id": item.id,
                "stage": item.stage,
                "risk": item.risk + " (недостаточно данных для проверки — заполните соответствующие поля в ANSWERS)",
                "recommendation": item.recommendation,
            })
    return triggered


if __name__ == "__main__":
    # ПРИМЕР: заполнить по конкретной заявке перед подачей
    ANSWERS = {
        "part1_all_docs_provided": True,
        "part1_contains_supplier_info_or_price": False,
        "info_verified_against_originals": True,
        "security_amount_required": 50000,
        "security_amount_paid": 50000,
        "using_bank_guarantee": False,
        "guarantee_matches_44fz_requirements": None,
        "part2_all_docs_provided": False,   # намеренно "плохой" пример, чтобы показать срабатывание
        "egrul_age_months": 8,
        "egrul_max_age_months_allowed": 6,
        "signatory_authority_valid": True,
    }

    results = run_checklist(ANSWERS)
    if not results:
        print("Рисков не обнаружено по заданным параметрам. Это не гарантия — только базовый слой проверки.")
    else:
        print(f"Обнаружено рисков: {len(results)}\n")
        for r in results:
            print(f"[{r['stage']}] {r['risk']}\n  -> {r['recommendation']}\n")

# Источники списка причин отклонения (проверено веб-поиском, август 2026):
# - https://saby.ru/articles/tenders/prichiny_otkloneniya_zayavok_44_fz
# - https://litender.ru/otklonenie-zayavki/
# - https://tenderoviki.ru/otklonenie-zayavki-po-44-fz-rasprostranennye-oshibki-uchastnikov.html
