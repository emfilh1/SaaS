"""
Карточка тендера с этапами (конвейер)
=========================================

Связывает разрозненные модули (Радар, антидемпинг/цена, документы) в один
путь ОДНОГО конкретного тендера — от первого обнаружения до готовой
заявки, вместо того чтобы держать в голове, на каком тендере что уже
сделано и что дальше.

Три рабочих этапа (как в описанном процессе):
1. Рассмотрение — карточка попала сюда (из Радара или вручную), решаем,
   смотреть дальше или нет.
2. Принятие решения по цене и участию — сюда стекаются антидемпинг и
   предварительная цена; переход на этот этап — естественная точка,
   чтобы отправить дайджест руководителю (bitrix24_client.push_executive_digest).
3. Подготовка документов — здесь подключается генератор документов.

Отдельно — "Отклонено", когда решили не участвовать (с указанием причины,
чтобы потом не наступать на те же грабли).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

ЭТАП_РАССМОТРЕНИЕ = "Рассмотрение"
ЭТАП_РЕШЕНИЕ = "Принятие решения по цене и участию"
ЭТАП_ДОКУМЕНТЫ = "Подготовка документов"
ЭТАП_ОТКЛОНЕНО = "Отклонено"

ЭТАПЫ_ПОРЯДОК = [ЭТАП_РАССМОТРЕНИЕ, ЭТАП_РЕШЕНИЕ, ЭТАП_ДОКУМЕНТЫ]


@dataclass
class StageEvent:
    stage: str
    timestamp: datetime
    note: str = ""


@dataclass
class TenderCard:
    reestr_number: str
    subject: str = ""
    customer_name: str = ""
    stage: str = ЭТАП_РАССМОТРЕНИЕ
    history: list[StageEvent] = field(default_factory=list)
    decision_note: str = ""       # по какой цене/на каких условиях решили участвовать
    rejection_reason: str = ""

    @property
    def rejected(self) -> bool:
        return self.stage == ЭТАП_ОТКЛОНЕНО

    def move_to(self, stage: str, note: str = "") -> None:
        self.stage = stage
        self.history.append(StageEvent(stage=stage, timestamp=datetime.now(), note=note))

    def advance(self, note: str = "") -> bool:
        """Переход на следующий этап по порядку. Возвращает False, если
        карточка уже на последнем этапе или отклонена — дальше двигать некуда."""
        if self.stage not in ЭТАПЫ_ПОРЯДОК:
            return False
        idx = ЭТАПЫ_ПОРЯДОК.index(self.stage)
        if idx + 1 >= len(ЭТАПЫ_ПОРЯДОК):
            return False
        self.move_to(ЭТАПЫ_ПОРЯДОК[idx + 1], note=note)
        return True

    def reject(self, reason: str) -> None:
        self.rejection_reason = reason
        self.move_to(ЭТАП_ОТКЛОНЕНО, note=reason)


def new_tender_card(reestr_number: str, subject: str = "", customer_name: str = "") -> TenderCard:
    card = TenderCard(reestr_number=reestr_number, subject=subject, customer_name=customer_name)
    card.move_to(ЭТАП_РАССМОТРЕНИЕ, note="Карточка создана")
    return card


if __name__ == "__main__":
    card = new_tender_card("ДЕМО-0000000000000000001", "Поставка металлопроката", "АО «Завод»")
    print(f"Создана карточка: этап «{card.stage}»")
    assert card.stage == ЭТАП_РАССМОТРЕНИЕ

    ok = card.advance(note="Решили участвовать, цена — 2.2 млн ₽")
    print(f"Переход на следующий этап: {ok}, теперь «{card.stage}»")
    assert ok and card.stage == ЭТАП_РЕШЕНИЕ

    ok = card.advance(note="Цена согласована")
    print(f"Переход на следующий этап: {ok}, теперь «{card.stage}»")
    assert ok and card.stage == ЭТАП_ДОКУМЕНТЫ

    ok = card.advance()
    print(f"Попытка перейти дальше последнего этапа: {ok}")
    assert not ok, "с последнего этапа двигаться некуда"

    print(f"\nИстория карточки ({len(card.history)} событий):")
    for event in card.history:
        print(f"  {event.timestamp.strftime('%H:%M:%S')} — {event.stage}" + (f" ({event.note})" if event.note else ""))

    card2 = new_tender_card("ДЕМО-0000000000000000002", "Поставка канцтоваров", "МУП")
    card2.reject("НМЦК ниже минимального порога компании")
    assert card2.rejected and card2.stage == ЭТАП_ОТКЛОНЕНО
    print(f"\nВторая карточка отклонена: {card2.rejection_reason}")

    print("\nПроверка пройдена: карточка и переходы между этапами работают корректно.")
