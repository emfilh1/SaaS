"""
Модели данных продукта: единый "язык", на котором говорят все модули
========================================================================

eis_client.py достаёт сырые извещения из ЕИС -> тут описано, во что их
превращает "Экстрактор требований" -> tender_application_linter.py
проверяет это на риски отклонения.

Это наша собственная схема (не государственная XML-схема ЕИС — та ещё не
изучена в деталях, увидим точные поля только когда получим реальный
архив через eis_client.py). Поэтому здесь без фантазий про то, что именно
лежит внутри архива ЕИС — только то, что нам нужно как результат.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class TenderNotice:
    """Базовая карточка тендера — то, что нужно для 'Радара', до глубокого разбора документации."""
    reestr_number: str                  # реестровый номер закупки в ЕИС
    customer_name: str                  # заказчик
    customer_inn: Optional[str]
    subject: str                        # предмет закупки (что покупают)
    nmck: Optional[float]               # начальная (максимальная) цена контракта, руб.
    okpd2_codes: list[str] = field(default_factory=list)
    region: Optional[str] = None
    submission_deadline: Optional[date] = None
    law: str = "44-ФЗ"                  # "44-ФЗ" или "223-ФЗ"


@dataclass
class TenderRequirements:
    """То, что 'Экстрактор требований' должен достать из документации закупки."""
    reestr_number: str

    # обеспечение
    application_security_amount: Optional[float] = None
    contract_security_amount: Optional[float] = None
    bank_guarantee_allowed: bool = True

    # антидемпинг (ст. 37 44-ФЗ) — включается, если предложенная цена участника
    # снижена относительно НМЦК на величину, установленную законом
    antidemping_threshold_percent: Optional[float] = None

    # документы, которые заказчик требует именно в этой закупке
    # (сверх стандартного пакета — стандартный уже учтён в линтере)
    required_documents: list[str] = field(default_factory=list)

    # формальные критерии к поставщику
    requires_sme_status: bool = False           # требование к статусу СМП/СОНКО
    requires_license: Optional[str] = None       # нужна ли лицензия и какая
    requires_experience: bool = False            # нужен опыт аналогичных поставок

    # условия исполнения
    delivery_deadline: Optional[date] = None
    warranty_period_months: Optional[int] = None

    # сколько дней нужно на изготовление номенклатуры этой закупки — оценка
    # ИИ по описанию (грубая, не инженерный расчёт). Точка расширения: когда
    # появится отдельная система планирования загрузки цеха, она должна
    # уметь заменить эту оценку реальным расчётом по факту текущей загрузки,
    # не меняя остальной код — интерфейс (Optional[int], дней) уже тот же.
    production_lead_time_days: Optional[int] = None

    # результат работы AI-экстрактора: что не удалось распознать уверенно —
    # чтобы не выдавать пользователю ложную уверенность
    low_confidence_fields: list[str] = field(default_factory=list)


@dataclass
class CompanyProfile:
    """Профиль компании-поставщика — настраиваемый слой (докручивается под клиента)."""
    name: str
    inn: str
    is_sme: bool = True
    licenses: list[str] = field(default_factory=list)
    okpd2_focus: list[str] = field(default_factory=list)   # чем компания торгует/производит
    egrul_extract_date: Optional[date] = None
    egrul_max_age_months_allowed_default: int = 6
