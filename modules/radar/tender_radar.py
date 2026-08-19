"""
Радар тендеров — модуль 1
=============================

Фильтрует и ранжирует поток извещений (TenderNotice из tender_models.py)
по факторам, которые волнуют конкретного поставщика: соответствие
номенклатуре, регион, размер контракта, срок на подачу заявки. Ставит
красные флаги там, где стоит присмотреться внимательнее, прежде чем
тратить время на разбор документации — например, нетиповая/сложная
номенклатура (по чертежам заказчика, с испытаниями, НИОКР и т.п.).

Два слоя фильтрации:
1. Детерминированный (всегда доступен, не требует ИИ и интернета) —
   по ключевым словам, ОКПД2, региону, срокам, размеру НМЦК. Основной
   рабочий слой — предсказуемый и проверяемый.
2. ИИ-слой (опциональный, по той же схеме, что в requirement_extractor.py:
   функция call_llm подставляется, по умолчанию — мок) — для случаев,
   когда ключевые слова не поймали сложность, а текст предмета закупки
   всё равно выглядит нетипично. Не обязателен: без него радар работает
   на первом слое.

Требует реального потока извещений из ЕИС (eis_client.py, нужен токен) —
пока работает на демонстрационном списке ниже, чтобы проверить логику
скоринга и красных флагов уже сейчас, без токена.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from modules.core.tender_models import TenderNotice

DEFAULT_COMPLEX_KEYWORDS = [
    "по чертежам заказчика", "индивидуальному чертежу", "нестандарт",
    "опытный образец", "испытани", "сертификац", "калибровк",
    "конструкторской документации", "ниокр", "спецификации заказчика",
]


@dataclass
class RadarPreferences:
    """Личные предпочтения поставщика — настраиваются один раз, дальше
    радар фильтрует поток извещений автоматически."""
    okpd2_focus: list[str] = field(default_factory=list)       # префиксы ОКПД2, которыми занимается компания
    preferred_regions: list[str] = field(default_factory=list)
    min_nmck: float = 0
    max_nmck: Optional[float] = None
    min_days_to_deadline: int = 3          # меньше — не успеть подготовить нормальную заявку
    complex_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_COMPLEX_KEYWORDS))
    laws: list[str] = field(default_factory=lambda: ["44-ФЗ", "223-ФЗ"])
    keyword_profiles: "list[KeywordProfile]" = field(default_factory=list)
    ai_search_query: str = ""  # свободный текст — "углублённый ИИ-поиск", когда списки слов не удобны


@dataclass
class KeywordProfile:
    """Именованный профиль поиска под одну номенклатурную группу — решает
    проблему омонимов вроде 'скобы измерительные' vs 'скобы для степлера':
    одно ключевое слово само по себе ничего не значит, поэтому профиль
    требует его (must_include) + хотя бы одно слово-подтверждение рядом
    (confirm_any), и сразу отсекает по словам-исключениям (exclude)."""
    name: str
    must_include: list[str] = field(default_factory=list)   # ВСЕ должны быть в тексте
    confirm_any: list[str] = field(default_factory=list)    # хотя бы ОДНО — снимает неоднозначность
    exclude: list[str] = field(default_factory=list)        # любое из этих — сразу мимо


@dataclass
class KeywordMatchResult:
    profile_name: str
    matched: bool
    confidence: str  # "высокая" | "низкая" (нужна проверка ИИ) | "нет"
    excluded_by: Optional[str] = None
    confirmed_by: list[str] = field(default_factory=list)


def match_keyword_profile(subject: str, profile: KeywordProfile) -> KeywordMatchResult:
    lowered = subject.lower()

    if profile.must_include and not all(kw.lower() in lowered for kw in profile.must_include):
        return KeywordMatchResult(profile.name, matched=False, confidence="нет")

    exclude_hit = next((kw for kw in profile.exclude if kw.lower() in lowered), None)
    if exclude_hit:
        return KeywordMatchResult(profile.name, matched=False, confidence="нет", excluded_by=exclude_hit)

    confirmed = [kw for kw in profile.confirm_any if kw.lower() in lowered]
    if confirmed or not profile.confirm_any:
        return KeywordMatchResult(profile.name, matched=True, confidence="высокая", confirmed_by=confirmed)

    return KeywordMatchResult(profile.name, matched=True, confidence="низкая")


KEYWORD_RELEVANCE_PROMPT = """Ты помогаешь производственной компании отличить нужную номенклатуру
от омонима с тем же словом в названии. Профиль поиска: "{profile_name}".
Обязательные слова профиля уже нашлись в предмете закупки, но ни одно
слово-подтверждение не встретилось — нужна твоя оценка по смыслу.

Предмет закупки: "{subject}"

Ответь только JSON без пояснений: {{"relevant": true/false, "reason": "краткое обоснование в одно предложение"}}"""


def _mock_relevance_llm(prompt: str) -> str:
    """Мок вместо реального вызова модели — как _mock_complexity_llm выше."""
    subject_start = prompt.rfind('Предмет закупки: "') + len('Предмет закупки: "')
    subject_end = prompt.find('"', subject_start)
    subject = prompt[subject_start:subject_end].lower()

    # эвристика для демо: слова из бытового/офисного контекста считаем не тем,
    # что нужно производственной компании — не идеально, но правдоподобно
    off_topic_words = ["офис", "канцеляр", "школ", "детск", "быт"]
    if any(w in subject for w in off_topic_words):
        return json.dumps({"relevant": False, "reason": "контекст бытовой/офисный, не похож на производственную номенклатуру"}, ensure_ascii=False)
    return json.dumps({"relevant": True, "reason": "по смыслу похоже на нужную номенклатуру, явных признаков другого назначения нет"}, ensure_ascii=False)


def verify_keyword_relevance_with_ai(subject: str, profile: KeywordProfile, call_llm: Callable[[str], str] = _mock_relevance_llm) -> dict:
    prompt = KEYWORD_RELEVANCE_PROMPT.format(profile_name=profile.name, subject=subject)
    raw = call_llm(prompt)
    try:
        data = json.loads(raw)
        return {"relevant": bool(data.get("relevant")), "reason": data.get("reason", "")}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"relevant": False, "reason": "не удалось разобрать ответ ИИ — считаем неопределённым"}


# ---------------------------------------- углублённый ИИ-поиск по свободному тексту

AI_SEARCH_PROMPT = """Ты помогаешь поставщику найти среди тендеров подходящие под свободное
описание того, что он ищет — понимая смысл, а не только точные слова
(например, запрос "измерительный инструмент" должен находить и "скобы
для контроля диаметра", даже без слова "измерительный" в тексте).

Запрос поставщика: "{query}"
Предмет закупки: "{subject}"

Подходит ли эта закупка под запрос? Ответь только JSON без пояснений:
{{"relevant": true/false, "reason": "краткое обоснование в одно предложение"}}"""


def _mock_search_llm(prompt: str) -> str:
    """Мок вместо реального вызова модели — простое совпадение по общим
    словам запроса и предмета закупки (без стоп-слов), как правдоподобная
    демонстрация конвейера без ключей API. Настоящая модель поймёт смысл
    точнее, чем пересечение слов."""
    query_start = prompt.find('Запрос поставщика: "') + len('Запрос поставщика: "')
    query_end = prompt.find('"', query_start)
    query = prompt[query_start:query_end].lower()

    subject_start = prompt.rfind('Предмет закупки: "') + len('Предмет закупки: "')
    subject_end = prompt.find('"', subject_start)
    subject = prompt[subject_start:subject_end].lower()

    stop_words = {"для", "и", "с", "по", "на", "не", "или", "из", "к", "от", "до"}
    query_words = {w for w in query.replace(",", " ").split() if len(w) > 2 and w not in stop_words}
    overlap = [w for w in query_words if w in subject]

    if overlap:
        return json.dumps({"relevant": True, "reason": f"совпадают слова: {', '.join(overlap)}"}, ensure_ascii=False)
    return json.dumps({"relevant": False, "reason": "явных пересечений с запросом не нашлось"}, ensure_ascii=False)


def search_relevance_with_ai(query: str, subject: str, call_llm: Callable[[str], str] = _mock_search_llm) -> dict:
    prompt = AI_SEARCH_PROMPT.format(query=query, subject=subject)
    raw = call_llm(prompt)
    try:
        data = json.loads(raw)
        return {"relevant": bool(data.get("relevant")), "reason": data.get("reason", "")}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"relevant": False, "reason": "не удалось разобрать ответ ИИ — считаем неопределённым"}


@dataclass
class TenderScore:
    tender: TenderNotice
    score: int
    red_flags: list[str] = field(default_factory=list)
    positive_reasons: list[str] = field(default_factory=list)
    days_to_deadline: Optional[int] = None


def score_tender(tender: TenderNotice, prefs: RadarPreferences, today: Optional[date] = None) -> TenderScore:
    today = today or date.today()
    score = 0
    red_flags: list[str] = []
    positives: list[str] = []

    if tender.law not in prefs.laws:
        red_flags.append(f"Закон {tender.law} не входит в отслеживаемые")

    if prefs.okpd2_focus:
        matched_codes = [c for c in tender.okpd2_codes if any(c.startswith(f) for f in prefs.okpd2_focus)]
        if matched_codes:
            score += 30
            positives.append(f"Совпадает по ОКПД2: {', '.join(matched_codes)}")
        else:
            red_flags.append("ОКПД2 не входит в номенклатуру компании")
    else:
        score += 10  # фокус не задан — не штрафуем, но и не поощряем

    if tender.region:
        if prefs.preferred_regions and tender.region in prefs.preferred_regions:
            score += 10
            positives.append(f"Регион «{tender.region}» в списке предпочтительных")
        elif prefs.preferred_regions:
            red_flags.append(f"Регион «{tender.region}» не в списке предпочтительных — учтите логистику")

    if tender.nmck is not None:
        if tender.nmck < prefs.min_nmck:
            red_flags.append(f"НМЦК {tender.nmck:,.0f} ₽ ниже минимального порога {prefs.min_nmck:,.0f} ₽".replace(",", " "))
        elif prefs.max_nmck is not None and tender.nmck > prefs.max_nmck:
            red_flags.append(f"НМЦК {tender.nmck:,.0f} ₽ выше комфортного максимума {prefs.max_nmck:,.0f} ₽".replace(",", " "))
        else:
            score += 15
    else:
        red_flags.append("НМЦК не указана в извещении — проверьте вручную")

    days_left = None
    if tender.submission_deadline:
        days_left = (tender.submission_deadline - today).days
        if days_left < 0:
            red_flags.append("Срок подачи заявки уже истёк")
        elif days_left < prefs.min_days_to_deadline:
            red_flags.append(f"На подготовку заявки осталось всего {days_left} дн.")
        else:
            score += 10

    subject_lower = tender.subject.lower()
    matched_kw = [kw for kw in prefs.complex_keywords if kw in subject_lower]
    if matched_kw:
        red_flags.append(f"Признаки сложной/нетиповой номенклатуры: {', '.join(matched_kw)}")
    else:
        score += 5

    for profile in prefs.keyword_profiles:
        match = match_keyword_profile(tender.subject, profile)
        if match.excluded_by:
            red_flags.append(f"Профиль «{profile.name}»: похоже на другое значение слова (нашлось «{match.excluded_by}») — скорее всего не то")
        elif match.matched and match.confidence == "высокая":
            score += 25
            positives.append(f"Профиль «{profile.name}» подтверждён: {', '.join(match.confirmed_by)}")
        elif match.matched:
            ai = verify_keyword_relevance_with_ai(tender.subject, profile)
            if ai["relevant"]:
                score += 10
                positives.append(f"Профиль «{profile.name}»: ИИ подтвердил релевантность — {ai['reason']}")
            else:
                red_flags.append(f"Профиль «{profile.name}»: ИИ считает нерелевантным — {ai['reason']}")

    if prefs.ai_search_query.strip():
        search_result = search_relevance_with_ai(prefs.ai_search_query, tender.subject)
        if search_result["relevant"]:
            score += 40
            positives.append(f"🤖 ИИ-поиск по запросу «{prefs.ai_search_query}»: {search_result['reason']}")
        else:
            red_flags.append(f"🤖 ИИ-поиск по запросу «{prefs.ai_search_query}»: не похоже — {search_result['reason']}")

    return TenderScore(
        tender=tender, score=score, red_flags=red_flags,
        positive_reasons=positives, days_to_deadline=days_left,
    )


def rank_tenders(tenders: list[TenderNotice], prefs: RadarPreferences, today: Optional[date] = None) -> list[TenderScore]:
    """Возвращает тендеры, отсортированные по убыванию score — лучшие совпадения первыми."""
    scored = [score_tender(t, prefs, today) for t in tenders]
    return sorted(scored, key=lambda s: s.score, reverse=True)


# ------------------------------------------------------------- ИИ-слой (опц.)

AI_COMPLEXITY_PROMPT = """Ты помогаешь производственной компании оценить закупку перед участием.
Прочитай предмет закупки и скажи, выглядит ли номенклатура нетипово сложной
для серийного производителя (например: единичное индивидуальное
изготовление по чужим чертежам, требует НИОКР, нестандартные испытания,
узкоспециализированная сертификация) — в отличие от обычной серийной
поставки стандартной продукции.

Предмет закупки: "{subject}"

Ответь только JSON без пояснений: {{"is_complex": true/false, "reason": "краткое обоснование в одно предложение"}}"""


def _mock_complexity_llm(prompt: str) -> str:
    """Мок вместо реального вызова модели — как _mock_llm в
    requirement_extractor.py. Правдоподобно реагирует на содержание
    промпта, чтобы конвейер можно было проверить без ключей API."""
    subject_start = prompt.find('Предмет закупки: "') + len('Предмет закупки: "')
    subject_end = prompt.find('"', subject_start)
    subject = prompt[subject_start:subject_end].lower()

    trigger_words = ["индивидуальн", "чертеж", "опытный", "испытан", "разработ", "нестандарт"]
    if any(w in subject for w in trigger_words):
        return json.dumps({
            "is_complex": True,
            "reason": "формулировка предмета закупки указывает на нетиповое изготовление, а не серийную поставку",
        }, ensure_ascii=False)
    return json.dumps({
        "is_complex": False,
        "reason": "предмет закупки похож на стандартную серийную поставку",
    }, ensure_ascii=False)


def assess_complexity_with_ai(subject: str, call_llm: Callable[[str], str] = _mock_complexity_llm) -> dict:
    prompt = AI_COMPLEXITY_PROMPT.format(subject=subject)
    raw = call_llm(prompt)
    try:
        data = json.loads(raw)
        return {"is_complex": bool(data.get("is_complex")), "reason": data.get("reason", "")}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"is_complex": False, "reason": "не удалось разобрать ответ ИИ — считаем неопределённым"}


# --------------------------------------------------------- демо-данные

def demo_tenders(today: Optional[date] = None) -> list[TenderNotice]:
    today = today or date.today()
    return [
        TenderNotice(
            reestr_number="0000000000000000001",
            customer_name="АО «Завод металлоконструкций»",
            customer_inn="7700000001",
            subject="Поставка металлопроката листового ГОСТ 19903-2015, серийная продукция",
            nmck=2_400_000,
            okpd2_codes=["25.11.23"],
            region="Московская область",
            submission_deadline=today + timedelta(days=12),
        ),
        TenderNotice(
            reestr_number="0000000000000000002",
            customer_name="ФГУП «Спецпроект»",
            customer_inn="7700000002",
            subject="Изготовление опытного образца детали по индивидуальному чертежу заказчика, с проведением испытаний",
            nmck=890_000,
            okpd2_codes=["25.62.20"],
            region="г. Москва",
            submission_deadline=today + timedelta(days=9),
        ),
        TenderNotice(
            reestr_number="0000000000000000003",
            customer_name="МУП «Городское хозяйство»",
            customer_inn="7700000003",
            subject="Поставка канцелярских товаров для нужд администрации",
            nmck=150_000,
            okpd2_codes=["17.23.13"],
            region="Тверская область",
            submission_deadline=today + timedelta(days=20),
        ),
        TenderNotice(
            reestr_number="0000000000000000004",
            customer_name="АО «Промышленный холдинг»",
            customer_inn="7700000004",
            subject="Поставка крепёжных изделий стандартных серий по ГОСТ, серийное производство",
            nmck=3_100_000,
            okpd2_codes=["25.94.11"],
            region="Московская область",
            submission_deadline=today + timedelta(days=2),
        ),
        TenderNotice(
            reestr_number="0000000000000000005",
            customer_name="ООО «Дальстройсервис»",
            customer_inn="7700000005",
            subject="Разработка конструкторской документации и изготовление нестандартного оборудования",
            nmck=None,
            okpd2_codes=["28.29.12"],
            region="Приморский край",
            submission_deadline=today + timedelta(days=25),
        ),
        TenderNotice(
            reestr_number="0000000000000000006",
            customer_name="АО «Металлсервис»",
            customer_inn="7700000006",
            subject="Поставка труб стальных электросварных по ГОСТ 10704-91",
            nmck=5_600_000,
            okpd2_codes=["24.20.11"],
            region="Московская область",
            submission_deadline=today + timedelta(days=18),
        ),
        # три тендера ниже — иллюстрация омонима "скобы" для профилей поиска
        TenderNotice(
            reestr_number="0000000000000000007",
            customer_name="ФГУП «Метрология»",
            customer_inn="7700000007",
            subject="Поставка скоб измерительных по ГОСТ 166 для контроля наружного диаметра",
            nmck=420_000,
            okpd2_codes=["26.51.53"],
            region="Московская область",
            submission_deadline=today + timedelta(days=15),
        ),
        TenderNotice(
            reestr_number="0000000000000000008",
            customer_name="МКУ «Школа-интернат»",
            customer_inn="7700000008",
            subject="Поставка скоб для степлера канцелярского офисного",
            nmck=15_000,
            okpd2_codes=["17.23.13"],
            region="Московская область",
            submission_deadline=today + timedelta(days=15),
        ),
        TenderNotice(
            reestr_number="0000000000000000009",
            customer_name="ООО «Инструмент-Сервис»",
            customer_inn="7700000009",
            subject="Поставка скоб для комплектации производственной линии",
            nmck=310_000,
            okpd2_codes=["28.29.12"],
            region="Московская область",
            submission_deadline=today + timedelta(days=15),
        ),
    ]


# полный текст документации для каждого демо-тендера — раньше при переносе
# карточки из Радара в "Разбор документации" переносился только предмет
# закупки одной строкой (Радар больше и не знает — как и в реальности,
# полная документация приходит только по факту скачивания с площадки).
# Для ДЕМО-набора эти тексты имитируют то, что реально скачали бы с ЕИС,
# чтобы весь путь по вкладкам можно было пройти по-настоящему, не вводя
# ничего руками — как только появится токен ЕИС, эта функция станет не
# нужна, её место займёт eis_client.py.
_DEMO_DOCUMENTATION_TEXTS: dict[str, str] = {
    "0000000000000000001": (
        "Извещение о проведении электронного аукциона. Предмет закупки: поставка металлопроката "
        "листового ГОСТ 19903-2015, серийная продукция. НМЦК 2 400 000 руб.\n"
        "Обеспечение заявки — 48 000 руб. Обеспечение исполнения контракта — 240 000 руб.\n"
        "Независимая гарантия допускается в качестве обеспечения исполнения контракта.\n"
        "Гарантийный срок на товар — 12 месяцев. Срок поставки — в течение 30 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ."
    ),
    "0000000000000000002": (
        "Извещение о проведении электронного аукциона. Предмет закупки: изготовление опытного образца "
        "детали по индивидуальному чертежу заказчика, с проведением испытаний. НМЦК 890 000 руб.\n"
        "Обеспечение заявки — 26 700 руб. Обеспечение исполнения контракта — 133 500 руб.\n"
        "Независимая гарантия не допускается в качестве обеспечения исполнения контракта.\n"
        "Гарантийный срок на товар — 6 месяцев. Срок поставки — в течение 45 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ, "
        "техническое задание с приложением протокола испытаний."
    ),
    "0000000000000000003": (
        "Извещение о проведении электронного аукциона. Предмет закупки: поставка канцелярских товаров "
        "для нужд администрации. НМЦК 150 000 руб.\n"
        "Обеспечение заявки не установлено. Обеспечение исполнения контракта — 15 000 руб.\n"
        "Гарантийный срок не установлен. Срок поставки — в течение 15 дней с даты заключения контракта.\n"
        "Закупка ограничена участием субъектов малого предпринимательства и СОНКО.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ."
    ),
    "0000000000000000004": (
        "Извещение о проведении электронного аукциона. Предмет закупки: поставка крепёжных изделий "
        "стандартных серий по ГОСТ, серийное производство. НМЦК 3 100 000 руб.\n"
        "Обеспечение заявки — 62 000 руб. Обеспечение исполнения контракта — 310 000 руб.\n"
        "Независимая гарантия допускается в качестве обеспечения исполнения контракта.\n"
        "Гарантийный срок на товар — 12 месяцев. Срок поставки — в течение 20 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ."
    ),
    "0000000000000000005": (
        "Извещение о проведении электронного аукциона. Предмет закупки: разработка конструкторской "
        "документации и изготовление нестандартного оборудования. НМЦК не указана в открытом доступе, "
        "уточняется по документации.\n"
        "Обеспечение заявки — 45 000 руб. Обеспечение исполнения контракта — 225 000 руб.\n"
        "Независимая гарантия не допускается в качестве обеспечения исполнения контракта.\n"
        "Гарантийный срок на оборудование — 24 месяца. Срок поставки — в течение 90 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ, "
        "техническое задание, комплект конструкторской документации."
    ),
    "0000000000000000006": (
        "Извещение о проведении электронного аукциона. Предмет закупки: поставка труб стальных "
        "электросварных по ГОСТ 10704-91. НМЦК 5 600 000 руб.\n"
        "Обеспечение заявки — 112 000 руб. Обеспечение исполнения контракта — 560 000 руб.\n"
        "Независимая гарантия допускается в качестве обеспечения исполнения контракта.\n"
        "Гарантийный срок на товар — 12 месяцев. Срок поставки — в течение 25 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ."
    ),
    "0000000000000000007": (
        "Извещение о проведении электронного аукциона. Предмет закупки: поставка скоб измерительных "
        "по ГОСТ 166 для контроля наружного диаметра. НМЦК 420 000 руб.\n"
        "Обеспечение заявки — 12 600 руб. Обеспечение исполнения контракта — 63 000 руб.\n"
        "Гарантийный срок на инструмент — 18 месяцев. Срок поставки — в течение 15 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ, "
        "копию свидетельства о поверке средств измерений."
    ),
    "0000000000000000008": (
        "Извещение о проведении запроса котировок. Предмет закупки: поставка скоб для степлера "
        "канцелярского офисного. НМЦК 15 000 руб.\n"
        "Обеспечение заявки не установлено. Обеспечение исполнения контракта не установлено.\n"
        "Гарантийный срок не установлен. Срок поставки — в течение 10 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ."
    ),
    "0000000000000000009": (
        "Извещение о проведении электронного аукциона. Предмет закупки: поставка скоб для комплектации "
        "производственной линии. НМЦК 310 000 руб.\n"
        "Обеспечение заявки — 9 300 руб. Обеспечение исполнения контракта — 46 500 руб.\n"
        "Гарантийный срок — 12 месяцев. Срок поставки — в течение 20 дней с даты заключения контракта.\n"
        "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия требованиям ст. 31 44-ФЗ."
    ),
}


def demo_documentation_text(reestr_number: str) -> Optional[str]:
    """Полный демо-текст документации для тендера из demo_tenders() по
    реестровому номеру — None, если номер не из демо-набора (например,
    добавлен вручную в Конвейере)."""
    return _DEMO_DOCUMENTATION_TEXTS.get(reestr_number)


if __name__ == "__main__":
    skoby_profile = KeywordProfile(
        name="Скобы измерительные",
        must_include=["скоб"],
        confirm_any=["измерительн", "штангенциркул", "калибр", "гост 166"],
        exclude=["степлер", "канцеляр", "зубн", "брекет", "ортодонт"],
    )
    prefs = RadarPreferences(
        okpd2_focus=["25."],
        preferred_regions=["Московская область", "г. Москва"],
        min_nmck=10_000,
        max_nmck=4_000_000,
        min_days_to_deadline=5,
        keyword_profiles=[skoby_profile],
    )
    ranked = rank_tenders(demo_tenders(), prefs)

    print(f"=== Радар: {len(ranked)} тендеров, отсортировано по score ===\n")
    for r in ranked:
        print(f"[{r.score:>3}] {r.tender.reestr_number} — {r.tender.subject[:60]}")
        for p in r.positive_reasons:
            print(f"        + {p}")
        for f in r.red_flags:
            print(f"        ! {f}")
        ai = assess_complexity_with_ai(r.tender.subject)
        print(f"        ИИ: {'сложная номенклатура' if ai['is_complex'] else 'типовая номенклатура'} — {ai['reason']}")
        print()

    assert ranked[0].score >= ranked[-1].score

    by_id = {r.tender.reestr_number: r for r in ranked}
    measuring = by_id["0000000000000000007"]
    stapler = by_id["0000000000000000008"]
    ambiguous = by_id["0000000000000000009"]

    assert any("подтверждён" in p for p in measuring.positive_reasons), "измерительные скобы должны подтвердиться профилем с высокой уверенностью"
    assert any("другое значение слова" in f for f in stapler.red_flags), "скобы для степлера должны быть отсечены по exclude"
    assert any("ИИ" in p or "ИИ" in f for p in ambiguous.positive_reasons for f in [""]) or \
        any("ИИ" in x for x in ambiguous.positive_reasons + ambiguous.red_flags), \
        "неоднозначный случай без подтверждения/исключения должен уйти на проверку ИИ"

    print("Проверка пройдена: плюс/минус-слова верно различают омоним «скобы».")
