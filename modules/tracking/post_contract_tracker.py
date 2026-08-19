"""
Пост-контрактный трекер
==========================

Модуль 5 продукта — последний из пяти. Как и "Калькулятор цены и рисков",
не требует ни AI, ни интернета: после победы в тендере у поставщика
появляется набор дедлайнов и обязательств, которые легко забыть среди
текучки, и именно этим объясняются частые проблемы после победы (штрафы
за просрочку поставки, незакрытые документы, не вовремя возвращённое
обеспечение). Этот модуль просто считает даты и говорит, что горит.

Берёт на вход Contract — контракт, который логично собирать из
TenderRequirements (уже извлечённых "Экстрактором") + даты подписания
+ фактическую цену и способ обеспечения (которые определит "Калькулятор
цены и рисков" из price_risk_calculator.py). Дальше — чистая арифметика
дат, без всякой магии.

Все статусы, типы событий и типы обеспечения — на русском (включая
внутренние строковые коды, не только тексты для показа), чтобы при
подключении интерфейса нигде не всплывали английские ярлыки/вкладки.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

DUE_SOON_THRESHOLD_DAYS = 7  # порог, после которого дедлайн считается "горящим"

# Типы обеспечения контракта
ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ = "деньги"              # на спецсчёте
ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ = "банковская_гарантия"

# Статусы события
СТАТУС_ВЫПОЛНЕНО = "выполнено"
СТАТУС_ПРОСРОЧЕНО = "просрочено"
СТАТУС_ГОРИТ = "горит"
СТАТУС_В_ГРАФИКЕ = "в_графике"
СТАТУС_БЕЗ_ДАТЫ = "нет_даты"

# Типы отслеживаемых событий
СОБЫТИЕ_ПОСТАВКА = "поставка"
СОБЫТИЕ_ЗАКРЫВАЮЩИЕ_ДОКУМЕНТЫ = "закрывающие_документы"
СОБЫТИЕ_ГАРАНТИЯ = "гарантия"
СОБЫТИЕ_ОБЕСПЕЧЕНИЕ = "обеспечение"


@dataclass
class Contract:
    reestr_number: str
    customer_name: str
    contract_price: float
    signing_date: date
    delivery_deadline: Optional[date] = None
    warranty_period_months: Optional[int] = None
    security_amount: Optional[float] = None
    security_type: str = ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ
    security_expiry_date: Optional[date] = None  # актуально для банковской гарантии
    completed_events: set[str] = field(default_factory=set)  # какие события пользователь уже отметил как сделанные


@dataclass
class TrackedEvent:
    event_type: str
    description: str
    due_date: Optional[date]
    days_remaining: Optional[int]
    status: str  # один из СТАТУС_*
    recommendation: str


def _status_for(due_date: Optional[date], today: date, is_done: bool) -> tuple[str, Optional[int]]:
    if is_done:
        return СТАТУС_ВЫПОЛНЕНО, None
    if due_date is None:
        return СТАТУС_БЕЗ_ДАТЫ, None
    days_remaining = (due_date - today).days
    if days_remaining < 0:
        return СТАТУС_ПРОСРОЧЕНО, days_remaining
    if days_remaining <= DUE_SOON_THRESHOLD_DAYS:
        return СТАТУС_ГОРИТ, days_remaining
    return СТАТУС_В_ГРАФИКЕ, days_remaining


def build_contract_from_requirements(
    reestr_number: str,
    customer_name: str,
    contract_price: float,
    signing_date: date,
    delivery_deadline: Optional[date],
    warranty_period_months: Optional[int],
    security_amount: Optional[float],
    security_type: str = ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ,
    security_expiry_date: Optional[date] = None,
) -> Contract:
    """Тонкая обёртка-конструктор — сюда удобно передать поля из
    TenderRequirements (tender_models.py), не переписывая их вручную."""
    return Contract(
        reestr_number=reestr_number,
        customer_name=customer_name,
        contract_price=contract_price,
        signing_date=signing_date,
        delivery_deadline=delivery_deadline,
        warranty_period_months=warranty_period_months,
        security_amount=security_amount,
        security_type=security_type,
        security_expiry_date=security_expiry_date,
    )


def get_tracked_events(contract: Contract, today: Optional[date] = None) -> list[TrackedEvent]:
    today = today or date.today()
    events: list[TrackedEvent] = []

    # 1. Срок поставки
    status, days = _status_for(contract.delivery_deadline, today, СОБЫТИЕ_ПОСТАВКА in contract.completed_events)
    events.append(TrackedEvent(
        event_type=СОБЫТИЕ_ПОСТАВКА,
        description="Поставка товара/выполнение работ по контракту",
        due_date=contract.delivery_deadline,
        days_remaining=days,
        status=status,
        recommendation="Подготовить товар/акт к отгрузке заранее — просрочка поставки грозит неустойкой по контракту.",
    ))

    # 2. Закрывающие документы — по практике готовятся вокруг даты поставки,
    # обычно с небольшим запасом на подписание сторонами (условно неделя)
    if contract.delivery_deadline:
        closing_due = contract.delivery_deadline + timedelta(days=7)
        status, days = _status_for(closing_due, today, СОБЫТИЕ_ЗАКРЫВАЮЩИЕ_ДОКУМЕНТЫ in contract.completed_events)
        events.append(TrackedEvent(
            event_type=СОБЫТИЕ_ЗАКРЫВАЮЩИЕ_ДОКУМЕНТЫ,
            description="Оформление закрывающих документов (акт приёмки, счёт-фактура/УПД)",
            due_date=closing_due,
            days_remaining=days,
            status=status,
            recommendation="Сверить состав закрывающих документов с условиями контракта заранее, не после поставки.",
        ))

    # 3. Гарантийный срок — не дедлайн для действия, а окно ответственности;
    # трекаем как напоминание о том, когда заканчиваются гарантийные обязательства
    if contract.warranty_period_months and contract.delivery_deadline:
        warranty_end = _add_months(contract.delivery_deadline, contract.warranty_period_months)
        status, days = _status_for(warranty_end, today, СОБЫТИЕ_ГАРАНТИЯ in contract.completed_events)
        events.append(TrackedEvent(
            event_type=СОБЫТИЕ_ГАРАНТИЯ,
            description=f"Окончание гарантийного периода ({contract.warranty_period_months} мес. с даты поставки)",
            due_date=warranty_end,
            days_remaining=days,
            status=status,
            recommendation="До этой даты сохранять готовность к гарантийным обращениям заказчика.",
        ))

    # 4. Возврат/продление обеспечения
    if contract.security_type == ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ and contract.security_expiry_date:
        status, days = _status_for(contract.security_expiry_date, today, СОБЫТИЕ_ОБЕСПЕЧЕНИЕ in contract.completed_events)
        events.append(TrackedEvent(
            event_type=СОБЫТИЕ_ОБЕСПЕЧЕНИЕ,
            description="Истечение срока банковской гарантии обеспечения контракта",
            due_date=contract.security_expiry_date,
            days_remaining=days,
            status=status,
            recommendation="Если контракт ещё не закрыт к этой дате — заранее продлить гарантию в банке, иначе заказчик вправе считать обеспечение отсутствующим.",
        ))
    elif contract.security_type == ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ and contract.delivery_deadline:
        # для денежного обеспечения на спецсчёте — напоминание проверить возврат после приёмки
        return_check_due = contract.delivery_deadline + timedelta(days=14)
        status, days = _status_for(return_check_due, today, СОБЫТИЕ_ОБЕСПЕЧЕНИЕ in contract.completed_events)
        events.append(TrackedEvent(
            event_type=СОБЫТИЕ_ОБЕСПЕЧЕНИЕ,
            description="Проверить возврат денежного обеспечения со спецсчёта после приёмки",
            due_date=return_check_due,
            days_remaining=days,
            status=status,
            recommendation="Обеспечение должно вернуться после подписания закрывающих документов — если этого не произошло, обратиться в банк/на площадку.",
        ))

    return events


def _add_months(base: date, months: int) -> date:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = min(base.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def summarize(events: list[TrackedEvent]) -> str:
    overdue = [e for e in events if e.status == СТАТУС_ПРОСРОЧЕНО]
    due_soon = [e for e in events if e.status == СТАТУС_ГОРИТ]
    lines = []
    if overdue:
        lines.append(f"ПРОСРОЧЕНО: {len(overdue)}")
    if due_soon:
        lines.append(f"Горит (≤{DUE_SOON_THRESHOLD_DAYS} дн.): {len(due_soon)}")
    if not overdue and not due_soon:
        lines.append("Срочных дедлайнов нет.")
    return " | ".join(lines)


if __name__ == "__main__":
    # Пример: контракт подписан сегодня минус 40 дней, поставка была назначена
    # через 30 дней от подписания (то есть уже 10 дней как просрочена) —
    # специально показываем "плохой" случай, чтобы видеть просрочку.
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

    events = get_tracked_events(contract, today=today)

    print(f"=== Контракт {contract.reestr_number}, заказчик: {contract.customer_name} ===")
    print(summarize(events))
    print()
    for e in events:
        due = e.due_date.isoformat() if e.due_date else "нет даты"
        print(f"[{e.status.upper()}] {e.description} (срок: {due}, дней осталось: {e.days_remaining})")
        print(f"  -> {e.recommendation}\n")
