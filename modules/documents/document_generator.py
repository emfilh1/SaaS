"""
Генератор типовых документов для заявки на участие в тендере
=================================================================

Модуль не сочиняет текст через ИИ — заполняет проверенные юристами
шаблоны данными компании и конкретной закупки. Результат — .docx
(Word), готовый к печати и подписи. Формулировки сверены веб-поиском
в августе 2026 (источники внизу файла).

Это не юридическая консультация: сгенерированный документ должен
проверить и подписать человек, ответственный за заявку — особенно
в нестандартных случаях (несколько учредителей с разными долями,
нетиповой устав и т.п.).

Важная оговорка про декларации (ст. 31 44-ФЗ и СМП): на большинстве
электронных площадок (ЕИС, РТС-тендер, Сбербанк-АСТ и т.д.) они
формируются автоматически в форме заявки при её подаче — отдельный
файл, как правило, не нужен. Прикладывайте сгенерированные здесь
файлы отдельно, только если закупка не электронная или документация
прямо требует отдельный файл. Решение об одобрении крупной сделки и
сопроводительное письмо этой оговорки не имеют — они нужны отдельным
файлом почти всегда, когда применимы.
"""

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

ФОРМА_ООО_ЕДИНСТВЕННЫЙ_УЧАСТНИК = "ООО, единственный участник"
ФОРМА_ООО_НЕСКОЛЬКО_УЧАСТНИКОВ = "ООО, несколько участников"
ФОРМА_ИП = "ИП"

КРУПНАЯ_СДЕЛКА_ПОРОГ_ДОЛЯ = 0.25  # ст. 46 ФЗ "Об ООО": 25% балансовой стоимости активов


@dataclass
class SupplierDetails:
    """Реквизиты поставщика для оформления документов. Отдельно от
    CompanyProfile (tender_models.py), чтобы юридические поля (ОГРН,
    адрес, форма собственности), нужные только здесь, не утяжеляли
    модель, которой пользуются остальные модули."""
    name: str
    inn: str
    ogrn: str = ""
    address: str = ""
    director_name: str = ""
    director_position: str = "Генеральный директор"
    legal_form: str = ФОРМА_ООО_ЕДИНСТВЕННЫЙ_УЧАСТНИК
    balance_sheet_assets: float = 0  # балансовая стоимость активов, ₽ — для расчёта крупной сделки


def _base_document() -> Document:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    section = doc.sections[0]
    section.left_margin = Cm(3)
    section.right_margin = Cm(1.5)
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    return doc


def _title(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(14)


def _money(amount: float) -> str:
    return f"{amount:,.0f} ₽".replace(",", " ")


def to_bytes(doc: Document) -> bytes:
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------ декларация ст. 31

def generate_declaration_31fz(supplier: SupplierDetails, reestr_number: str, decl_date: date) -> Document:
    doc = _base_document()
    _title(doc, "ДЕКЛАРАЦИЯ")
    _title(doc, "о соответствии участника закупки требованиям, установленным")
    _title(doc, "пунктами 3–5, 7–11 части 1 статьи 31 Федерального закона от 05.04.2013 № 44-ФЗ")
    doc.add_paragraph()
    doc.add_paragraph(f"по закупке № {reestr_number}")
    doc.add_paragraph()
    doc.add_paragraph(
        f"{supplier.name} (ИНН {supplier.inn}) настоящим декларирует, что по состоянию "
        f"на дату подачи заявки:"
    )
    points = [
        "не находится в процессе ликвидации (для юридического лица), не признан несостоятельным (банкротом);",
        "деятельность участника закупки не приостановлена в порядке, предусмотренном "
        "Кодексом Российской Федерации об административных правонарушениях, на дату подачи заявки;",
        "у участника закупки отсутствует недоимка по налогам, сборам, задолженность по иным "
        "обязательным платежам в бюджеты бюджетной системы Российской Федерации, размер которой "
        "превышает 25 процентов балансовой стоимости активов участника закупки по данным "
        "бухгалтерской отчётности за последний отчётный период;",
        "у руководителя, членов коллегиального исполнительного органа, лица, исполняющего функции "
        "единоличного исполнительного органа, или главного бухгалтера участника закупки — "
        "юридического лица отсутствует судимость за преступления в сфере экономики и (или) "
        "преступления, предусмотренные статьями 289, 290, 291, 291.1 Уголовного кодекса "
        "Российской Федерации;",
        "участник закупки — юридическое лицо в течение двух лет до момента подачи заявки не "
        "привлекалось к административной ответственности за совершение административного "
        "правонарушения, предусмотренного статьёй 19.28 Кодекса Российской Федерации об "
        "административных правонарушениях;",
        "отсутствует конфликт интересов между участником закупки и заказчиком;",
        "участник закупки не является офшорной компанией;",
        "в отношении участника закупки отсутствуют ограничения для участия в закупках, "
        "установленные законодательством Российской Федерации.",
    ]
    for i, text in enumerate(points, start=1):
        doc.add_paragraph(f"{i}. {text}")
    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {decl_date.strftime('%d.%m.%Y')}")
    doc.add_paragraph()
    doc.add_paragraph(f"{supplier.director_position} ____________________ / {supplier.director_name or 'ФИО'} /")
    return doc


# ---------------------------------------------------------- декларация СМП

def generate_sme_declaration(supplier: SupplierDetails, reestr_number: str, decl_date: date) -> Document:
    doc = _base_document()
    _title(doc, "ДЕКЛАРАЦИЯ")
    _title(doc, "о соответствии участника закупки критериям отнесения к субъектам")
    _title(doc, "малого предпринимательства (ст. 4 Федерального закона от 24.07.2007 № 209-ФЗ)")
    doc.add_paragraph()
    doc.add_paragraph(f"по закупке № {reestr_number}")
    doc.add_paragraph()
    doc.add_paragraph(
        f"{supplier.name} (ИНН {supplier.inn}, ОГРН {supplier.ogrn or '[ОГРН]'}) настоящим "
        f"заявляет, что является субъектом малого предпринимательства, поскольку по итогам "
        f"предшествующего календарного года:"
    )
    doc.add_paragraph("— среднесписочная численность работников не превышает 100 человек;")
    doc.add_paragraph("— доход от предпринимательской деятельности не превышает 800 млн рублей.")
    doc.add_paragraph()
    doc.add_paragraph(
        f"Сведения о {supplier.name} включены в Единый реестр субъектов малого и среднего "
        f"предпринимательства (ФНС России)."
    )
    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {decl_date.strftime('%d.%m.%Y')}")
    doc.add_paragraph()
    doc.add_paragraph(f"{supplier.director_position} ____________________ / {supplier.director_name or 'ФИО'} /")
    return doc


# ------------------------------------------------------- крупная сделка

def generate_major_transaction_document(
    supplier: SupplierDetails,
    reestr_number: str,
    deal_amount: float,
    deal_subject: str,
    city: str,
    doc_date: date,
) -> tuple[Document, str]:
    """Тип документа подбирается автоматически: ИП -> справка о
    неприменимости; ООО с суммой сделки ниже 25% активов -> справка об
    отсутствии признаков; ООО с суммой выше порога -> решение/протокол
    об одобрении. Возвращает (документ, человекочитаемое название типа)."""

    if supplier.legal_form == ФОРМА_ИП:
        doc = _base_document()
        _title(doc, "СПРАВКА")
        _title(doc, "о неприменимости требований об одобрении крупной сделки")
        doc.add_paragraph()
        doc.add_paragraph(
            f"ИП {supplier.name} (ИНН {supplier.inn}) сообщает, что понятие «крупная сделка» "
            f"в значении статьи 46 Федерального закона от 08.02.1998 № 14-ФЗ «Об обществах с "
            f"ограниченной ответственностью» и статьи 78 Федерального закона от 26.12.1995 "
            f"№ 208-ФЗ «Об акционерных обществах» к индивидуальным предпринимателям не "
            f"применяется, поскольку эти нормы регулируют деятельность хозяйственных обществ."
        )
        doc.add_paragraph()
        doc.add_paragraph(f"По закупке № {reestr_number} на сумму {_money(deal_amount)}.")
        doc.add_paragraph()
        doc.add_paragraph(f"{city}, {doc_date.strftime('%d.%m.%Y')}")
        doc.add_paragraph()
        doc.add_paragraph(f"ИП ____________________ / {supplier.director_name or supplier.name} /")
        return doc, "Справка о неприменимости (ИП)"

    threshold = supplier.balance_sheet_assets * КРУПНАЯ_СДЕЛКА_ПОРОГ_ДОЛЯ
    is_major = supplier.balance_sheet_assets > 0 and deal_amount >= threshold

    if not is_major:
        doc = _base_document()
        _title(doc, "СПРАВКА")
        _title(doc, "об отсутствии признаков крупной сделки")
        doc.add_paragraph()
        note = ""
        if supplier.balance_sheet_assets <= 0:
            note = " (балансовая стоимость активов не указана — уточните перед подачей, если сумма сделки значительная)"
        doc.add_paragraph(
            f"{supplier.name} (ИНН {supplier.inn}) сообщает, что сделка по результатам участия "
            f"в закупке № {reestr_number} на сумму {_money(deal_amount)} не является для "
            f"Общества крупной сделкой в смысле статьи 46 Федерального закона от 08.02.1998 "
            f"№ 14-ФЗ «Об обществах с ограниченной ответственностью», поскольку не превышает "
            f"25% балансовой стоимости активов Общества ({_money(threshold)} по данным "
            f"бухгалтерской отчётности за последний отчётный период){note}."
        )
        doc.add_paragraph(
            "В связи с этим одобрение сделки в порядке, предусмотренном законодательством об "
            "одобрении крупных сделок, не требуется."
        )
        doc.add_paragraph()
        doc.add_paragraph(f"{city}, {doc_date.strftime('%d.%m.%Y')}")
        doc.add_paragraph()
        doc.add_paragraph(f"{supplier.director_position} ____________________ / {supplier.director_name or 'ФИО'} /")
        return doc, "Справка об отсутствии признаков крупной сделки"

    doc = _base_document()
    if supplier.legal_form == ФОРМА_ООО_НЕСКОЛЬКО_УЧАСТНИКОВ:
        _title(doc, "ПРОТОКОЛ")
        _title(doc, "общего собрания участников об одобрении крупной сделки")
        doc.add_paragraph()
        doc.add_paragraph(f"{supplier.name} (ИНН {supplier.inn})")
        doc.add_paragraph(f"{city}                                                    {doc_date.strftime('%d.%m.%Y')}")
        doc.add_paragraph()
        doc.add_paragraph("Повестка дня: об одобрении крупной сделки.")
        doc.add_paragraph(
            f"Решили: одобрить совершение Обществом крупной сделки — заключение договора "
            f"(контракта) по результатам участия в закупке № {reestr_number}, предметом которой "
            f"является {deal_subject}, на сумму, не превышающую {_money(deal_amount)}."
        )
        doc.add_paragraph(
            f"Уполномочить на подписание указанного договора: "
            f"{supplier.director_position} {supplier.director_name or '[ФИО]'}."
        )
        doc.add_paragraph()
        doc.add_paragraph("Председатель собрания ____________________ / ФИО /")
        doc.add_paragraph("Секретарь собрания ____________________ / ФИО /")
        return doc, "Протокол общего собрания участников"

    _title(doc, "РЕШЕНИЕ")
    _title(doc, "единственного участника об одобрении крупной сделки")
    doc.add_paragraph()
    doc.add_paragraph(f"{supplier.name} (ИНН {supplier.inn})")
    doc.add_paragraph(f"{city}                                                    {doc_date.strftime('%d.%m.%Y')}")
    doc.add_paragraph()
    doc.add_paragraph(
        f"Я, {supplier.director_name or '[ФИО]'}, являясь единственным участником {supplier.name} "
        f"(ИНН {supplier.inn}, ОГРН {supplier.ogrn or '[ОГРН]'}), решил:"
    )
    doc.add_paragraph(
        f"1. Одобрить совершение Обществом крупной сделки — заключение договора (контракта) по "
        f"результатам участия в закупке № {reestr_number}, предметом которой является "
        f"{deal_subject}, на сумму, не превышающую {_money(deal_amount)}."
    )
    doc.add_paragraph(
        f"2. Уполномочить на подписание указанного договора: "
        f"{supplier.director_position} {supplier.director_name or '[ФИО]'}."
    )
    doc.add_paragraph()
    doc.add_paragraph(f"Единственный участник ____________________ / {supplier.director_name or 'ФИО'} /")
    return doc, "Решение единственного участника"


# --------------------------------------------------- сопроводительное письмо

def generate_cover_letter(
    supplier: SupplierDetails,
    reestr_number: str,
    customer_name: str,
    documents: list[str],
    city: str,
    letter_date: date,
) -> Document:
    doc = _base_document()
    doc.add_paragraph(f"Исх. № ___ от {letter_date.strftime('%d.%m.%Y')}")
    doc.add_paragraph()
    doc.add_paragraph(f"Заказчику: {customer_name or '[наименование заказчика]'}")
    doc.add_paragraph()
    _title(doc, "СОПРОВОДИТЕЛЬНОЕ ПИСЬМО")
    doc.add_paragraph()
    doc.add_paragraph(
        f"{supplier.name} (ИНН {supplier.inn}) направляет заявку на участие в закупке "
        f"№ {reestr_number}. В составе заявки прилагаются следующие документы:"
    )
    if documents:
        for i, d in enumerate(documents, start=1):
            doc.add_paragraph(f"{i}. {d}")
    else:
        doc.add_paragraph("[список документов — заполните после разбора документации закупки на вкладке «Разбор документации»]")
    doc.add_paragraph()
    doc.add_paragraph(f"{supplier.director_position} ____________________ / {supplier.director_name or 'ФИО'} /")
    doc.add_paragraph()
    doc.add_paragraph(f"{city}, {letter_date.strftime('%d.%m.%Y')}")
    return doc


# ----------------------------------------------------- протокол разногласий

@dataclass
class DisagreementItem:
    """Одна строка протокола разногласий — один спорный пункт проекта контракта."""
    clause: str            # пункт проекта контракта (например, "п. 4.2")
    customer_wording: str  # редакция заказчика
    supplier_wording: str  # предлагаемая редакция участника
    justification: str     # обоснование (со ссылкой на извещение/документацию/заявку)


def generate_disagreement_protocol(
    supplier: SupplierDetails,
    reestr_number: str,
    customer_name: str,
    items: list[DisagreementItem],
    protocol_date: date,
) -> Document:
    """Единой утверждённой формы у протокола разногласий по 44-ФЗ нет — состав
    произвольный, но должен явно указывать на противоречие между проектом
    контракта и извещением/документацией/заявкой участника (это и есть
    основание для внесения изменения, а не просто "нам не нравится").
    Подать нужно через ЭТП в течение 5 рабочих дней с момента получения
    проекта контракта — этот файл прикладывается к тому обращению."""
    doc = _base_document()
    _title(doc, "ПРОТОКОЛ РАЗНОГЛАСИЙ")
    _title(doc, "к проекту контракта")
    doc.add_paragraph()
    doc.add_paragraph(f"по закупке № {reestr_number}")
    doc.add_paragraph(f"Заказчик: {customer_name or '[наименование заказчика]'}")
    doc.add_paragraph(f"Участник: {supplier.name} (ИНН {supplier.inn})")
    doc.add_paragraph()
    doc.add_paragraph(
        "В соответствии с частью 4 статьи 83.2 Федерального закона от 05.04.2013 № 44-ФЗ "
        "участник, с которым заключается контракт, при наличии разногласий по проекту "
        "контракта, направленному заказчиком, составляет настоящий протокол разногласий "
        "с указанием положений проекта контракта, не соответствующих извещению об "
        "осуществлении закупки, документации о закупке и (или) своей заявке."
    )
    doc.add_paragraph()

    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for cell, text in zip(header_cells, ["№ п/п", "Пункт проекта контракта / редакция заказчика", "Предлагаемая редакция участника", "Обоснование"]):
        cell.text = text
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True

    if items:
        for i, item in enumerate(items, start=1):
            row = table.add_row().cells
            row[0].text = str(i)
            row[1].text = f"{item.clause}: {item.customer_wording}"
            row[2].text = item.supplier_wording
            row[3].text = item.justification
    else:
        row = table.add_row().cells
        row[0].text = "1"
        row[1].text = "[пункт проекта контракта, вызывающий разногласия]"
        row[2].text = "[предлагаемая формулировка]"
        row[3].text = "[ссылка на извещение/документацию/заявку, обосновывающая изменение]"

    doc.add_paragraph()
    doc.add_paragraph(
        "Просим рассмотреть настоящий протокол разногласий в срок, установленный частью 4 "
        "статьи 83.2 Федерального закона от 05.04.2013 № 44-ФЗ, и направить доработанный "
        "проект контракта либо мотивированный отказ."
    )
    doc.add_paragraph()
    doc.add_paragraph(f"Дата: {protocol_date.strftime('%d.%m.%Y')}")
    doc.add_paragraph()
    doc.add_paragraph(f"{supplier.director_position} ____________________ / {supplier.director_name or 'ФИО'} /")
    return doc


# ------------------------------------ сопоставление требуемых документов

# ключевые слова ищем без учёта регистра в тексте, который "Экстрактор требований"
# достал из документации закупки (TenderRequirements.required_documents)
_ШАБЛОН_КЛЮЧЕВЫЕ_СЛОВА = [
    ("31fz", ["ст. 31", "статье 31", "31 44-фз", "п.1 ч.1 ст.31"]),
    ("sme", ["смп", "малого предпринимат", "сонко"]),
    ("major_transaction", ["крупн", "одобрени"]),
    ("cover_letter", ["сопроводительн", "опись документ"]),
    ("disagreement_protocol", ["разногласи"]),
]

ШАБЛОН_НАЗВАНИЕ = {
    "31fz": "Декларация ст. 31 44-ФЗ",
    "sme": "Декларация СМП",
    "major_transaction": "Решение/справка о крупной сделке",
    "cover_letter": "Сопроводительное письмо",
    "disagreement_protocol": "Протокол разногласий",
}


def match_required_documents(required_documents: list[str]) -> list[dict]:
    """Для каждого документа, который 'Экстрактор требований' нашёл в
    документации закупки, определяет: можем ли мы сгенерировать его сами
    (по ключевым словам) или это готовый документ/файл, который нужно
    просто приложить вручную (лицензия, сертификат, выписка ЕГРЮЛ и т.п. —
    их не сгенерировать, они у поставщика уже есть или должны быть заказаны)."""
    results = []
    for doc_name in required_documents:
        lowered = doc_name.lower()
        matched_key = next(
            (key for key, keywords in _ШАБЛОН_КЛЮЧЕВЫЕ_СЛОВА if any(kw in lowered for kw in keywords)),
            None,
        )
        results.append({
            "required": doc_name,
            "template_key": matched_key,
            "template_name": ШАБЛОН_НАЗВАНИЕ.get(matched_key),
            "auto_generatable": matched_key is not None,
        })
    return results


if __name__ == "__main__":
    demo_supplier = SupplierDetails(
        name="ООО «Квалитетпром» (пример)",
        inn="0000000000",
        ogrn="0000000000000",
        director_name="Иванов Иван Иванович",
        director_position="Генеральный директор",
        legal_form=ФОРМА_ООО_ЕДИНСТВЕННЫЙ_УЧАСТНИК,
        balance_sheet_assets=3_000_000,
    )
    today = date.today()

    docs = {
        "declaration_31fz.docx": generate_declaration_31fz(demo_supplier, "ДЕМО-0000000000000000000", today),
        "sme_declaration.docx": generate_sme_declaration(demo_supplier, "ДЕМО-0000000000000000000", today),
        "cover_letter.docx": generate_cover_letter(
            demo_supplier, "ДЕМО-0000000000000000000", "ДЕМО Заказчик (пример)",
            ["Выписка из ЕГРЮЛ", "Декларация соответствия требованиям ст. 31 44-ФЗ"],
            "Москва", today,
        ),
        "disagreement_protocol.docx": generate_disagreement_protocol(
            demo_supplier, "ДЕМО-0000000000000000000", "ДЕМО Заказчик (пример)",
            [DisagreementItem(
                clause="п. 4.2",
                customer_wording="Срок поставки — 5 календарных дней с даты заключения контракта",
                supplier_wording="Срок поставки — 15 календарных дней с даты заключения контракта",
                justification="Не соответствует извещению: срок поставки в извещении указан как 01.10.2026, а не 5 дней с даты заключения контракта",
            )],
            today,
        ),
    }
    major_doc, major_label = generate_major_transaction_document(
        demo_supplier, "ДЕМО-0000000000000000000", 1_200_000, "поставка оборудования", "Москва", today,
    )
    print(f"Тип документа о крупной сделке при активах 3 млн ₽ и сделке 1.2 млн ₽: {major_label}")
    assert major_label == "Решение единственного участника", "1.2 млн >= 25% от 3 млн (750 тыс) — должно быть решение"
    docs["major_transaction.docx"] = major_doc

    for filename, document in docs.items():
        data = to_bytes(document)
        assert len(data) > 0
        print(f"{filename}: {len(data)} байт — сгенерирован без ошибок")

    print("\nПроверка пройдена: все документы генерируются корректно.")

    print("\n=== Сопоставление требуемых документов с шаблонами ===")
    matched = match_required_documents([
        "Выписка из ЕГРЮЛ",
        "Декларация соответствия требованиям ст. 31 44-ФЗ",
        "Копия лицензии на осуществление деятельности",
    ])
    for m in matched:
        status = m["template_name"] if m["auto_generatable"] else "нет шаблона — приложить вручную"
        print(f"  {m['required']!r} -> {status}")
    assert matched[0]["auto_generatable"] is False, "выписку ЕГРЮЛ не генерируем"
    assert matched[1]["template_key"] == "31fz"
    assert matched[2]["auto_generatable"] is False, "лицензию не генерируем"
    print("Проверка сопоставления пройдена.")

# Источники (проверено веб-поиском, август 2026):
# - https://ppt.ru/art/zakupki/obrazets-deklaratsii-o-sootvetstvii-uchastnika-zakupki-trebovaniyam-44-fz (декларация ст. 31)
# - https://www.malyi-biznes.ru/deklaraciya-o-prinadlezhnosti-k-subektam-malogo-predprinimatelstva/ (декларация СМП)
# - https://www.26-2.ru/art/357381-kriterii-malogo-biznesa (актуальные пороги МСП: 800 млн ₽ для малых предприятий)
# - https://saby.ru/articles/tenders/odobrenie_krupnoj_sdelki (решение об одобрении крупной сделки, порог 25%)
# - https://www.pro-goszakaz.ru/article/103385-reshenie-ob-odobrenii-krupnoy-sdelki-po-44-fz-godu-poryadok-i-obrazets
