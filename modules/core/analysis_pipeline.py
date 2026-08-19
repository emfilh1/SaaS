"""
Сборка всего конвейера: от текста документации до готовой проверки рисков
============================================================================

Текст документации -> requirement_extractor (AI) -> TenderRequirements
    -> answers_from_requirements() сводит это с профилем компании
    -> tender_application_linter проверяет риски отклонения

Это то, что должно происходить внутри продукта одним нажатием кнопки.
Сейчас — рабочий скелет на моковом LLM, без интерфейса. Как только
появится реальный документ и токен ЕИС (eis_client.py), сюда просто
подставляются реальные данные вместо мока и демо-профиля.
"""

from datetime import date

from modules.core.tender_models import TenderRequirements, CompanyProfile
from modules.core.requirement_extractor import extract_requirements, _mock_llm
from modules.compliance.tender_application_linter import run_checklist


def answers_from_requirements(reqs: TenderRequirements, company: CompanyProfile) -> dict:
    """Сводит требования конкретного тендера + профиль компании в формат,
    который понимает линтер (tender_application_linter.ANSWERS).

    Часть полей линтера (part1_all_docs_provided, info_verified_against_originals
    и т.п.) нельзя вывести автоматически — они про факт сборки конкретной заявки,
    а не про требования закупки. Такие поля оставляем None: интерфейс продукта
    должен будет спросить их у пользователя явно, а не подставлять наугад."""

    egrul_age_months = None
    if company.egrul_extract_date:
        egrul_age_months = (date.today() - company.egrul_extract_date).days // 30

    return {
        # выводится из требований тендера + профиля компании
        "security_amount_required": reqs.application_security_amount,
        # использует ли компания банковскую гарантию — решение заявителя, а не
        # требование тендера, из reqs его вывести нельзя (bank_guarantee_allowed
        # говорит только о том, разрешена ли она документацией)
        "using_bank_guarantee": None,
        "guarantee_matches_44fz_requirements": None,  # требует отдельной проверки текста гарантии — не автоматизируется здесь
        "egrul_age_months": egrul_age_months,
        "egrul_max_age_months_allowed": company.egrul_max_age_months_allowed_default,

        # это про сборку конкретной заявки — продукт должен спросить пользователя,
        # а не додумывать сам
        "part1_all_docs_provided": None,
        "part1_contains_supplier_info_or_price": None,
        "info_verified_against_originals": None,
        "security_amount_paid": None,
        "part2_all_docs_provided": None,
        "signatory_authority_valid": None,
    }


def run_pipeline_demo():
    demo_text = (
        "ДЕМО-ТЕКСТ (не настоящая документация закупки, только для проверки конвейера). "
        "Извещение о проведении электронного аукциона. Обеспечение заявки — 45 000 руб. "
        "Обеспечение исполнения контракта — 180 000 руб. Гарантийный срок — 12 месяцев. "
        "Срок поставки — до 01.10.2026. Участие только для субъектов МСП."
    )

    reqs = extract_requirements(
        reestr_number="ДЕМО-0000000000000000000",
        document_text=demo_text,
        call_llm=_mock_llm,
    )

    company = CompanyProfile(
        name="ДЕМО ООО (пример, не реальный профиль Квалитетпрома)",
        inn="0000000000",
        is_sme=True,
        egrul_extract_date=date(2025, 10, 1),  # пример: выписке уже больше 6 месяцев -> линтер должен это поймать
    )

    answers = answers_from_requirements(reqs, company)
    # поля про сборку конкретной заявки для демо просто проставим руками —
    # в реальном продукте это будут ответы пользователя в интерфейсе
    answers.update({
        "part1_all_docs_provided": True,
        "part1_contains_supplier_info_or_price": False,
        "info_verified_against_originals": True,
        "security_amount_paid": 45000,
        "part2_all_docs_provided": True,
        "signatory_authority_valid": True,
    })

    print("=== Извлечённые требования тендера ===")
    print(reqs)
    print("\n=== Сведённые ответы для линтера ===")
    print(answers)

    results = run_checklist(answers)
    print(f"\n=== Результат линтера: {len(results)} риск(ов) ===")
    for r in results:
        print(f"[{r['stage']}] {r['risk']}\n  -> {r['recommendation']}\n")


if __name__ == "__main__":
    run_pipeline_demo()

    # Как переключиться с мока на реальную модель, когда появится ключ и документ:
    #
    #   import os
    #   from yandexgpt_client import call_yandexgpt
    #   from functools import partial
    #
    #   real_llm = partial(call_yandexgpt, api_key=os.environ["YANDEX_API_KEY"], folder_id=os.environ["YANDEX_FOLDER_ID"])
    #   reqs = extract_requirements(reestr_number="...", document_text=реальный_текст, call_llm=real_llm)
    #
    # Для GigaChat — аналогично, через gigachat_client.call_gigachat(credentials=...).
    # Остальной код (tender_models, tender_application_linter) менять не нужно.
