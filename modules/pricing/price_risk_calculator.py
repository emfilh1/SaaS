"""
Калькулятор цены и рисков: антидемпинговые меры по ст. 37 44-ФЗ
====================================================================

Модуль 4 продукта. В отличие от остальных модулей — не требует ни AI, ни
интернета, ни токенов: это чистая логика закона. Отвечает на вопрос
"если мы предложим такую-то цену и выиграем — что нам придётся сделать
с обеспечением, и не потеряем ли мы аванс".

Правила (проверено веб-поиском, источник указан внизу файла):

Антидемпинг включается, если предложенная участником цена НИЖЕ НМЦК
на 25% и более (и это конкурс или аукцион — на электронный запрос
котировок правило не распространяется).

Если НМЦК > 15 млн ₽:
    выбора нет — обеспечение исполнения контракта обязано быть
    не меньше, чем МАКСИМУМ из (1.5 x обеспечение, указанное в извещении)
    и (10% от НМЦК); также должно быть не меньше суммы аванса.
    Аванс при этом НЕ выплачивается.

Если НМЦК <= 15 млн ₽:
    участник выбирает сам:
      вариант 1 — то же самое, что и для НМЦК > 15 млн (повышенное обеспечение);
      вариант 2 — обычное обеспечение (как в извещении) + подтверждение
      добросовестности: 3 контракта за последние 3 года, исполненные без
      неустоек, из них хотя бы один — на сумму не менее 20% от текущего НМЦК.

Отдельно: для закупок только среди СМП/СОНКО участник может быть вообще
освобождён от обеспечения при тех же 3 контрактах на сумму не менее НМЦК —
это не реализовано ниже как отдельная ветка (см. TODO), чтобы не
множить недопроверенные частные случаи, только упомянуто в заметках.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AntidempingResult:
    triggered: bool
    discount_percent: float
    nmck_bracket: str  # "свыше_15млн" или "до_15млн"
    required_security_options: list[dict] = field(default_factory=list)
    advance_allowed: Optional[bool] = None
    notes: list[str] = field(default_factory=list)


def calculate_antidemping(
    nmck: float,
    notice_security_amount: float,
    proposed_price: float,
    advance_amount: float = 0,
    has_three_qualifying_contracts: Optional[bool] = None,  # None = неизвестно, продукт должен спросить
) -> AntidempingResult:
    if nmck <= 0:
        raise ValueError("НМЦК должна быть положительным числом")

    discount_percent = round((1 - proposed_price / nmck) * 100, 2)
    triggered = discount_percent >= 25

    if not triggered:
        return AntidempingResult(
            triggered=False,
            discount_percent=discount_percent,
            nmck_bracket="свыше_15млн" if nmck > 15_000_000 else "до_15млн",
            notes=["Снижение цены меньше 25% — антидемпинговые меры по ст. 37 44-ФЗ не применяются."],
        )

    increased_security = max(notice_security_amount * 1.5, nmck * 0.10)
    increased_security = max(increased_security, advance_amount)

    if nmck > 15_000_000:
        return AntidempingResult(
            triggered=True,
            discount_percent=discount_percent,
            nmck_bracket="свыше_15млн",
            required_security_options=[{
                "method": "увеличенное обеспечение (обязательно, выбора нет)",
                "required_security": round(increased_security, 2),
                "formula": "max(1.5 × обеспечение из извещения, 10% от НМЦК, сумма аванса)",
            }],
            advance_allowed=False,
            notes=["НМЦК > 15 млн ₽: аванс по контракту не выплачивается (ч. 13 ст. 37 44-ФЗ), даже если он предусмотрен документацией."],
        )

    # НМЦК <= 15 млн — есть выбор из двух вариантов
    options = [{
        "method": "вариант 1: увеличенное обеспечение",
        "required_security": round(increased_security, 2),
        "formula": "max(1.5 × обеспечение из извещения, 10% от НМЦК, сумма аванса)",
    }]

    good_faith_note = (
        "нужно подтвердить 3 контракта за последние 3 года, исполненных без неустоек, "
        "хотя бы один — на сумму не менее 20% от текущего НМЦК"
    )
    if has_three_qualifying_contracts is True:
        options.append({
            "method": "вариант 2: обычное обеспечение + подтверждение добросовестности",
            "required_security": notice_security_amount,
            "condition": good_faith_note,
            "eligible": True,
        })
    elif has_three_qualifying_contracts is False:
        options.append({
            "method": "вариант 2: обычное обеспечение + подтверждение добросовестности",
            "condition": good_faith_note,
            "eligible": False,
            "reason": "по имеющимся данным подходящих контрактов нет — вариант недоступен",
        })
    else:
        options.append({
            "method": "вариант 2: обычное обеспечение + подтверждение добросовестности",
            "condition": good_faith_note,
            "eligible": None,
            "reason": "неизвестно, есть ли у компании 3 таких контракта — нужно уточнить у пользователя",
        })

    return AntidempingResult(
        triggered=True,
        discount_percent=discount_percent,
        nmck_bracket="до_15млн",
        required_security_options=options,
        advance_allowed=None,  # зависит от выбранного варианта — не берёмся утверждать без уточнения
        notes=["НМЦК ≤ 15 млн ₽: участник сам выбирает между увеличенным обеспечением и подтверждением добросовестности."],
    )


if __name__ == "__main__":
    # Контрольные примеры с известным ответом. Каждый подобран так, чтобы
    # проверять свою часть формулы по отдельности — если поменять любую
    # константу (25%, 15 млн, 1.5×, 10%, max/min) хотя бы один пример
    # сломается. Это и есть "проверка с режимом порчи": тест бесполезен,
    # если он проходит одинаково что с правильной, что с испорченной
    # формулой — здесь такого нет ни у одного примера.

    # 1) Контрольный пример из реального разбора юристов (сверено с источником):
    # НМЦК 6 000 000, обеспечение в извещении 300 000, снижение 28% ->
    # ожидаемый ответ: 600 000 (10% от НМЦК больше, чем 1.5 × 300 000 = 450 000)
    r1 = calculate_antidemping(nmck=6_000_000, notice_security_amount=300_000, proposed_price=6_000_000 * 0.72)
    assert r1.triggered is True
    assert r1.nmck_bracket == "до_15млн"
    assert r1.required_security_options[0]["required_security"] == 600_000, "10% от НМЦК должен победить 1.5×обеспечение"

    # 2) Тот же порог, но со связывающим 1.5×обеспечение (не 10% от НМЦК) —
    # если бы в формуле max() был заменён на min(), или 1.5 на 1.0, эта
    # проверка провалится, а пример (1) её не заметит.
    r2 = calculate_antidemping(nmck=6_000_000, notice_security_amount=1_000_000, proposed_price=6_000_000 * 0.72)
    assert r2.required_security_options[0]["required_security"] == 1_500_000, "1.5×обеспечение (1.5 млн) должно победить 10% от НМЦК (600 тыс)"

    # 3) Связывающий член — сумма аванса, а не обеспечение/НМЦК.
    r3 = calculate_antidemping(nmck=6_000_000, notice_security_amount=300_000, proposed_price=6_000_000 * 0.72, advance_amount=700_000)
    assert r3.required_security_options[0]["required_security"] == 700_000, "аванс (700 тыс) должен победить и 1.5×обеспечение, и 10% от НМЦК"

    # 4) НМЦК строго выше 15 млн — обязательное повышенное обеспечение, аванс запрещён.
    r4 = calculate_antidemping(nmck=20_000_000, notice_security_amount=500_000, proposed_price=20_000_000 * 0.70)
    assert r4.nmck_bracket == "свыше_15млн"
    assert r4.required_security_options[0]["required_security"] == 2_000_000, "10% от 20 млн = 2 млн должно победить 1.5×500 тыс = 750 тыс"
    assert r4.advance_allowed is False, "при НМЦК > 15 млн аванс обязан быть запрещён"
    assert len(r4.required_security_options) == 1, "при НМЦК > 15 млн выбора вариантов быть не должно"

    # 5) Граница ровно 25% — порог включительный ("снижение 25% и более").
    r5 = calculate_antidemping(nmck=1_000_000, notice_security_amount=100_000, proposed_price=750_000)
    assert r5.discount_percent == 25.0
    assert r5.triggered is True, "снижение ровно 25% обязано включать антидемпинг (порог включительный)"

    # 6) Чуть ниже границы — антидемпинг не должен включаться.
    r6 = calculate_antidemping(nmck=1_000_000, notice_security_amount=100_000, proposed_price=750_100)
    assert r6.triggered is False, "снижение 24.99% не должно включать антидемпинг"

    # 7) Ветки подтверждения добросовестности для НМЦК ≤ 15 млн: True/False/None
    # должны давать три разных состояния варианта 2, а не молча совпадать.
    common = dict(nmck=8_000_000, notice_security_amount=200_000, proposed_price=8_000_000 * 0.70)
    r7_true = calculate_antidemping(**common, has_three_qualifying_contracts=True)
    r7_false = calculate_antidemping(**common, has_three_qualifying_contracts=False)
    r7_none = calculate_antidemping(**common, has_three_qualifying_contracts=None)
    assert r7_true.required_security_options[1]["eligible"] is True
    assert r7_false.required_security_options[1]["eligible"] is False
    assert r7_none.required_security_options[1]["eligible"] is None
    assert r7_true.required_security_options[1]["required_security"] == 200_000, "при подтверждённой добросовестности обеспечение — как в извещении, без увеличения"

    # 8) Некорректный вход должен явно падать, а не тихо считать мусор.
    try:
        calculate_antidemping(nmck=0, notice_security_amount=100_000, proposed_price=50_000)
        raise AssertionError("НМЦК = 0 должна была вызвать ValueError")
    except ValueError:
        pass

    print("Все 8 контрольных примеров (включая режим порчи) пройдены.")

    print("\n=== Пример для наглядности: НМЦК ≤ 15 млн, добросовестность неизвестна ===")
    print(r7_none)

# Источники (проверено веб-поиском, август 2026):
# - https://fz44.org/articles/antidempingovye-mery/ (подробный разбор + пример расчёта)
# - https://zakupki44fz.ru/voprosy-otvety/statya-37-antidempingovye-mery-pri-provedenii-konkursa-i-aukcziona/ (контрольный пример 6 млн/28%)
# - https://www.consultant.ru/document/cons_doc_LAW_144624/61657e3f731b9c26e662efa54b60c51fd48fded0/ (текст статьи 37)
