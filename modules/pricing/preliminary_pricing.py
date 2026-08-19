"""
Предварительное ценообразование по заказу
=============================================

Черновой калькулятор: себестоимость по статьям затрат + целевая наценка
= предварительная цена, которую можно предложить в заявке. Дополнительно
сверяет результат с антидемпинговым порогом (ст. 37 44-ФЗ), если известна
НМЦК закупки — переиспользует ту же логику, что и price_risk_calculator.py.

Это заготовка, а не окончательный прайсинг: калькулятор принимает уже
готовый список статей затрат (материалы, работы, накладные и т.д.) и не
знает и не обязан знать, откуда они взялись. Сейчас их вводят вручную в
интерфейсе — когда появится внутреннее приложение с реальной
себестоимостью номенклатуры, достаточно будет подставлять список
CostItem оттуда вместо ручного ввода, сама функция calculate_price не
изменится.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class CostItem:
    name: str
    amount: float


@dataclass
class PriceEstimate:
    cost_items: list[CostItem]
    total_cost: float
    margin_percent: float
    suggested_price: float
    nmck: Optional[float] = None
    discount_vs_nmck_percent: Optional[float] = None
    antidemping_warning: Optional[str] = None


def calculate_price(
    cost_items: list[CostItem],
    margin_percent: float,
    nmck: Optional[float] = None,
) -> PriceEstimate:
    if margin_percent < 0:
        raise ValueError("Наценка не может быть отрицательной")
    if any(item.amount < 0 for item in cost_items):
        raise ValueError("Статьи затрат не могут быть отрицательными")

    total_cost = sum(item.amount for item in cost_items)
    suggested_price = round(total_cost * (1 + margin_percent / 100), 2)

    discount = None
    warning = None
    if nmck and nmck > 0:
        discount = round((1 - suggested_price / nmck) * 100, 2)
        if discount >= 25:
            warning = (
                f"Предложенная цена ниже НМЦК на {discount:.1f}% — это включает антидемпинговые "
                f"меры по ст. 37 44-ФЗ (порог 25%). Проверьте требуемое обеспечение на вкладке «Антидемпинг»."
            )

    return PriceEstimate(
        cost_items=cost_items,
        total_cost=total_cost,
        margin_percent=margin_percent,
        suggested_price=suggested_price,
        nmck=nmck,
        discount_vs_nmck_percent=discount,
        antidemping_warning=warning,
    )


# --------------------------------------------------- черновая ИИ-оценка статей

AI_COST_ESTIMATE_PROMPT = """Ты помогаешь производственной компании грубо прикинуть себестоимость
заказа по требованиям тендера — это ЧЕРНОВАЯ оценка для затравки
калькулятора, не точный расчёт (точные цифры появятся, когда подключится
внутреннее приложение с реальной себестоимостью номенклатуры).

Требования тендера: "{context}"
Обеспечение контракта (ориентир масштаба сделки, обычно 5-30% от цены контракта): {security_amount}

Оцени долю каждой статьи затрат от общей себестоимости и саму общую
себестоимость по порядку величины. Проценты должны давать в сумме 100.

Ответь только JSON без пояснений:
{{"total_cost_estimate": число, "materials_percent": число, "labor_percent": число, "overhead_percent": число}}"""


def _mock_cost_estimate_llm(prompt: str) -> str:
    """Мок вместо реального вызова модели — как остальные моки в проекте.
    Берёт обеспечение контракта как ориентир масштаба (типичное соотношение
    обеспечение/цена контракта — около 15%) и раскладывает по трём статьям
    в правдоподобной для производственной компании пропорции."""
    marker = "Обеспечение контракта (ориентир масштаба сделки, обычно 5-30% от цены контракта): "
    start = prompt.find(marker) + len(marker)
    end = prompt.find("\n", start)
    try:
        security_amount = float(prompt[start:end].strip())
    except ValueError:
        security_amount = 0

    total_cost_estimate = security_amount / 0.15 * 0.75 if security_amount > 0 else 1_000_000
    return json.dumps({
        "total_cost_estimate": round(total_cost_estimate, -3),
        "materials_percent": 60,
        "labor_percent": 25,
        "overhead_percent": 15,
    }, ensure_ascii=False)


def estimate_cost_items_with_ai(
    context: str,
    security_amount: Optional[float] = None,
    call_llm: Callable[[str], str] = _mock_cost_estimate_llm,
) -> list[CostItem]:
    """Черновая раскладка себестоимости по трём статьям для затравки
    калькулятора — не точный расчёт, см. докстринг модуля и AI_COST_ESTIMATE_PROMPT."""
    prompt = AI_COST_ESTIMATE_PROMPT.format(context=context, security_amount=security_amount or 0)
    raw = call_llm(prompt)
    try:
        data = json.loads(raw)
        total = float(data.get("total_cost_estimate", 0))
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        total = 1_000_000
        data = {"materials_percent": 60, "labor_percent": 25, "overhead_percent": 15}

    return [
        CostItem("Материалы (черновая ИИ-оценка)", round(total * data.get("materials_percent", 60) / 100, -2)),
        CostItem("Работы (черновая ИИ-оценка)", round(total * data.get("labor_percent", 25) / 100, -2)),
        CostItem("Накладные расходы (черновая ИИ-оценка)", round(total * data.get("overhead_percent", 15) / 100, -2)),
    ]


if __name__ == "__main__":
    items = [
        CostItem("Материалы (металлопрокат)", 800_000),
        CostItem("Работы (изготовление)", 300_000),
        CostItem("Накладные расходы", 100_000),
    ]
    estimate = calculate_price(items, margin_percent=15, nmck=1_500_000)
    print("=== Предварительная цена заказа ===")
    for item in estimate.cost_items:
        print(f"  {item.name}: {item.amount:,.0f} ₽".replace(",", " "))
    print(f"Себестоимость: {estimate.total_cost:,.0f} ₽".replace(",", " "))
    print(f"Наценка: {estimate.margin_percent}%")
    print(f"Предварительная цена: {estimate.suggested_price:,.0f} ₽".replace(",", " "))
    if estimate.antidemping_warning:
        print(f"⚠️ {estimate.antidemping_warning}")
    else:
        print("Антидемпинг не срабатывает при этой цене.")

    expected_price = 1_200_000 * 1.15
    assert estimate.suggested_price == round(expected_price, 2), "себестоимость 1.2 млн + 15% должна дать 1 380 000"
    assert estimate.antidemping_warning is None, "снижение (1.38/1.5=8%) не должно триггерить антидемпинг"

    print("\n=== Пример с большим снижением (демпинг) ===")
    cheap_items = [CostItem("Материалы", 400_000), CostItem("Работы", 100_000)]
    cheap_estimate = calculate_price(cheap_items, margin_percent=5, nmck=1_500_000)
    print(f"Предварительная цена: {cheap_estimate.suggested_price:,.0f} ₽".replace(",", " "))
    print(f"⚠️ {cheap_estimate.antidemping_warning}")
    assert cheap_estimate.antidemping_warning is not None

    print("\n=== ИИ-оценка статей затрат (мок) ===")
    ai_items = estimate_cost_items_with_ai("Поставка металлопроката, серийная продукция", security_amount=180_000)
    for item in ai_items:
        print(f"  {item.name}: {item.amount:,.0f} ₽".replace(",", " "))
    total_ai = sum(i.amount for i in ai_items)
    print(f"Итого черновая себестоимость: {total_ai:,.0f} ₽".replace(",", " "))
    assert len(ai_items) == 3
    assert total_ai > 0

    print("\nПроверка пройдена.")
