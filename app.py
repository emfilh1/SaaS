"""
Демо-интерфейс: AI-помощник для участия в тендерах (сторона поставщика)
==========================================================================

Веб-обёртка поверх пакета modules/ (см. README.md за схемой структуры) —
чтобы видеть результат каждого модуля в браузере, а не в консоли print().
Сама бизнес-логика живёт в modules/*, этот файл — только интерфейс и склейка
данных между вкладками.

Запуск:
    pip install -r requirements.txt
    streamlit run app.py

По умолчанию работает на моковом LLM (см. modules.core.requirement_extractor._mock_llm) —
реальные ключи YandexGPT/GigaChat вводятся в сайдбаре и сохраняются между
запусками (modules/settings/local_settings.py), без изменений в коде.

Интерфейс целиком на русском, включая скрытые системные элементы Streamlit —
кнопка Deploy и меню-гамбургер спрятаны точечным CSS ниже (см. также
.streamlit/config.toml). Важно: НЕ прятать весь [data-testid="stToolbar"] —
внутри него же лежит кнопка возврата свёрнутой боковой панели, один раз
уже случайно спрятали и её вместе с Deploy.
"""

from datetime import date, timedelta
from functools import partial
from io import BytesIO
import zipfile

import streamlit as st

from modules.core.tender_models import TenderRequirements, CompanyProfile
from modules.core.requirement_extractor import extract_requirements, _mock_llm, build_digest, build_eis_notice_url
from modules.compliance.tender_application_linter import CHECKLIST, run_checklist
from modules.core.analysis_pipeline import answers_from_requirements
from modules.pricing.price_risk_calculator import calculate_antidemping, AntidempingResult
from modules.tracking.post_contract_tracker import (
    build_contract_from_requirements,
    get_tracked_events,
    summarize,
    ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ,
    ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ,
    СОБЫТИЕ_ПОСТАВКА,
    СОБЫТИЕ_ЗАКРЫВАЮЩИЕ_ДОКУМЕНТЫ,
    СОБЫТИЕ_ГАРАНТИЯ,
    СОБЫТИЕ_ОБЕСПЕЧЕНИЕ,
    СТАТУС_ВЫПОЛНЕНО,
    СТАТУС_ПРОСРОЧЕНО,
    СТАТУС_ГОРИТ,
    СТАТУС_В_ГРАФИКЕ,
)
from modules.tracking.ics_export import build_ics
from modules.integrations.bitrix24_client import push_tracked_events, push_executive_digest
from modules.documents.document_generator import (
    SupplierDetails,
    DisagreementItem,
    to_bytes,
    generate_declaration_31fz,
    generate_sme_declaration,
    generate_major_transaction_document,
    generate_cover_letter,
    generate_disagreement_protocol,
    match_required_documents,
    ФОРМА_ООО_ЕДИНСТВЕННЫЙ_УЧАСТНИК,
    ФОРМА_ООО_НЕСКОЛЬКО_УЧАСТНИКОВ,
    ФОРМА_ИП,
)
from modules.radar.tender_radar import RadarPreferences, KeywordProfile, rank_tenders, demo_tenders, assess_complexity_with_ai, demo_documentation_text
from modules.workflow.tender_pipeline import (
    TenderCard,
    new_tender_card,
    ЭТАП_РАССМОТРЕНИЕ,
    ЭТАП_РЕШЕНИЕ,
    ЭТАП_ДОКУМЕНТЫ,
    ЭТАПЫ_ПОРЯДОК,
)
from modules.pricing.preliminary_pricing import CostItem, calculate_price, estimate_cost_items_with_ai
from modules.documents.document_text_extractor import extract_text_from_upload
from modules.settings.local_settings import load_settings, save_settings, PERSISTED_KEYS
from modules.drawings.drawing_anonymizer import (
    CodeMapping,
    generate_internal_code,
    redact_image,
    registry_to_csv,
    suggest_text_regions_ocr,
    draw_suggestion_overlay,
)
from PIL import Image
from streamlit_drawable_canvas import st_canvas

# streamlit-drawable-canvas не обновлялся под новые версии Streamlit: внутри
# он дёргает streamlit.elements.image.image_to_url(image, width, clamp,
# channels, output_format, image_id), а в установленной версии Streamlit эта
# функция переехала в streamlit.elements.lib.image_utils и вместо width
# принимает объект LayoutConfig. Возвращаем совместимую обёртку под старую
# сигнатуру, которую ждёт canvas-пакет.
import streamlit.elements.image as _st_image_compat
from streamlit.elements.lib.image_utils import image_to_url as _image_to_url_new
from streamlit.elements.lib.layout_utils import LayoutConfig as _LayoutConfig


def _image_to_url_shim(image, width, clamp, channels, output_format, image_id):
    return _image_to_url_new(image, _LayoutConfig(width=width), clamp, channels, output_format, image_id)


_st_image_compat.image_to_url = _image_to_url_shim

st.set_page_config(page_title="Тендер-помощник — демо", page_icon="📋", layout="wide")

st.session_state.setdefault("tender_cards", {})  # reestr_number -> TenderCard, живёт весь сеанс

# настройки интеграций (ключи ИИ, вебхук Bitrix24) переживают перезапуск сервера —
# иначе после каждого обновления кода их приходится вбивать заново, а мы правим
# код часто; сам файл в .gitignore, секреты никуда не публикуются
if not st.session_state.get("_settings_loaded"):
    for _k, _v in load_settings().items():
        st.session_state.setdefault(_k, _v)
    st.session_state["_settings_loaded"] = True

# ---------------------------------------------------------------- оформление

st.markdown(
    """
    <style>
    /* Прячем только англоязычные "Deploy" и меню-гамбургер — специально НЕ трогаем
       весь [data-testid="stToolbar"], потому что в нём же лежит кнопка возврата
       свёрнутой боковой панели (stExpandSidebarButton): спрятав контейнер целиком,
       один раз уже случайно спрятали и её — панель было невозможно развернуть обратно. */
    [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], footer {visibility: hidden;}
    .block-container {padding-top: 2rem; max-width: 1200px;}

    .badge {
        display: inline-block; padding: 3px 11px; border-radius: 999px;
        font-size: 0.82rem; font-weight: 600; line-height: 1.6;
    }
    .badge-success  {background:#DCFCE7; color:#166534;}
    .badge-warning  {background:#FEF3C7; color:#92400E;}
    .badge-danger   {background:#FEE2E2; color:#991B1B;}
    .badge-info     {background:#DBEAFE; color:#1E40AF;}
    .badge-neutral  {background:#E2E8F0; color:#334155;}

    .module-pill {
        display:flex; align-items:center; gap:8px; padding:8px 12px;
        border-radius:10px; background:#F8FAFC; border:1px solid #E2E8F0;
        margin-bottom:6px; font-size:0.87rem;
    }
    .module-pill b {font-weight:600;}

    .event-card {
        border:1px solid #E2E8F0; border-radius:12px; padding:14px 16px;
        margin-bottom:10px; background:#FFFFFF;
    }
    .event-card.overdue {border-left:4px solid #DC2626;}
    .event-card.soon    {border-left:4px solid #D97706;}
    .event-card.ontrack {border-left:4px solid #2563EB;}
    .event-card.done    {border-left:4px solid #16A34A; opacity:0.7;}
    .event-card.nodate  {border-left:4px solid #94A3B8;}

    .hero-caption {color:#475569; font-size:1.02rem; margin-top:-8px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def badge(text: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'


def sync_default(key: str, source_value) -> None:
    """Держит st.session_state[key] в синхроне с source_value (данные из
    другой вкладки — конвейера, прошлого расчёта и т.д.), но перезаписывает
    его только когда source_value РЕАЛЬНО изменился с прошлого раза.

    Нужно из-за двух конфликтующих особенностей Streamlit: если у виджета
    нет key — value= перестаёт применяться при повторных запусках, если
    другой виджет с тем же текстом подписи и тем же value= уже отрисован
    (совпадает автоматически вычисляемый ID, падает
    StreamlitDuplicateElementId). Если key есть, но нет этой синхронизации —
    value= вообще перестаёт что-либо менять после первого рендера, поле
    "залипает". Вызывать ПЕРЕД созданием виджета с этим key."""
    sentinel_key = f"_sync_seen_{key}"
    if st.session_state.get(sentinel_key) != source_value:
        st.session_state[key] = source_value
        st.session_state[sentinel_key] = source_value


DEMO_TEXT = (
    "Извещение о проведении электронного аукциона.\n"
    "Обеспечение заявки — 45 000 руб. Обеспечение исполнения контракта — 180 000 руб.\n"
    "Независимая гарантия не допускается в качестве обеспечения исполнения контракта.\n"
    "Гарантийный срок на товар — 12 месяцев. Срок поставки — до 01.10.2026.\n"
    "Участие в закупке ограничено только для субъектов МСП и СОНКО.\n"
    "Участник обязан предоставить: выписку из ЕГРЮЛ, декларацию соответствия "
    "требованиям ст. 31 44-ФЗ, копию лицензии на осуществление деятельности "
    "(при наличии лицензируемых работ)."
)

APPLICATION_FIELDS = [
    ("part1_all_docs_provided", "Все документы первой части предоставлены", True),
    ("part1_contains_supplier_info_or_price", "В первой части случайно есть данные поставщика/цена", False),
    ("info_verified_against_originals", "Сведения в заявке сверены с оригиналами документов", True),
    ("part2_all_docs_provided", "Все документы второй части предоставлены", True),
    ("signatory_authority_valid", "Полномочия подписанта (доверенность/приказ) действительны", True),
]


# --------------------------------------------------------------- рендеринг


def render_requirements(reqs: TenderRequirements) -> None:
    st.subheader("Извлечённые требования тендера")

    digest_col, link_col = st.columns([4, 1])
    with digest_col:
        st.caption("Выжимка (можно скопировать одним куском, например для коллеги)")
        st.code(build_digest(reqs), language=None)
    with link_col:
        st.write("")
        st.write("")
        st.link_button("🔗 Открыть в ЕИС", build_eis_notice_url(reqs.reestr_number), width="stretch")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Обеспеч. заявки", f"{reqs.application_security_amount / 1000:.0f} тыс ₽" if reqs.application_security_amount else "—")
    c2.metric("Обеспеч. контракта", f"{reqs.contract_security_amount / 1000:.0f} тыс ₽" if reqs.contract_security_amount else "—")
    c3.metric("Антидемпинг", f"{reqs.antidemping_threshold_percent:.0f}%" if reqs.antidemping_threshold_percent is not None else "—")
    c4.metric("Гарантия, мес.", reqs.warranty_period_months if reqs.warranty_period_months is not None else "—")
    c5.metric("Срок изготовления", f"{reqs.production_lead_time_days} дн." if reqs.production_lead_time_days is not None else "—")

    c5, c6, c7 = st.columns(3)
    c5.write(f"**Банковская гарантия допускается:** {'да' if reqs.bank_guarantee_allowed else 'нет'}")
    c6.write(f"**Только для СМП/СОНКО:** {'да' if reqs.requires_sme_status else 'нет'}")
    c7.write(f"**Срок поставки:** {reqs.delivery_deadline.strftime('%d.%m.%Y') if reqs.delivery_deadline else '—'}")

    if reqs.requires_license:
        st.write(f"**Требуется лицензия:** {reqs.requires_license}")
    if reqs.requires_experience:
        st.write("**Требуется опыт аналогичных поставок:** да")

    if reqs.required_documents:
        st.write("**Документы, которые требует именно эта закупка:**")
        for doc in reqs.required_documents:
            st.write(f"- {doc}")

    if reqs.low_confidence_fields:
        st.warning(
            "ИИ извлёк эти поля неуверенно — проверьте вручную по документации: "
            + ", ".join(reqs.low_confidence_fields)
        )


def render_risks(results: list[dict]) -> None:
    st.subheader("Результат проверки на риски отклонения")
    if not results:
        st.success("Рисков не обнаружено по заданным параметрам. Это не гарантия приёмки — только базовый слой проверки.")
        return
    st.markdown(badge(f"Найдено рисков: {len(results)}", "danger"), unsafe_allow_html=True)
    st.write("")
    for r in results:
        with st.container(border=True):
            st.markdown(f"{badge(r['stage'], 'neutral')} &nbsp; **{r['risk']}**", unsafe_allow_html=True)
            st.caption(f"Рекомендация: {r['recommendation']}")


def render_antidemping(result: AntidempingResult) -> None:
    st.subheader("Результат расчёта")
    c1, c2, c3 = st.columns(3)
    c1.metric("Снижение цены", f"{result.discount_percent:.1f}%")
    c2.metric("Порог НМЦК", "> 15 млн ₽" if result.nmck_bracket == "свыше_15млн" else "≤ 15 млн ₽")
    c3.metric("Антидемпинг", "включён" if result.triggered else "не включён")

    if not result.triggered:
        st.success(result.notes[0] if result.notes else "Антидемпинговые меры не применяются.")
        return

    st.warning("Антидемпинговые меры по ст. 37 44-ФЗ применяются к этой заявке.")
    if result.advance_allowed is False:
        st.error("Аванс по контракту НЕ выплачивается (ч. 13 ст. 37 44-ФЗ), даже если он предусмотрен документацией.")

    for opt in result.required_security_options:
        with st.container(border=True):
            st.markdown(f"**{opt['method']}**")
            if "required_security" in opt:
                st.markdown(f"Требуемое обеспечение: **{opt['required_security']:,.0f} ₽**".replace(",", " "))
            if "formula" in opt:
                st.caption(f"Формула: {opt['formula']}")
            if "condition" in opt:
                st.caption(f"Условие: {opt['condition']}")
            if opt.get("eligible") is True:
                st.markdown(badge("доступно", "success"), unsafe_allow_html=True)
            elif opt.get("eligible") is False:
                st.markdown(badge("недоступно: " + opt.get("reason", ""), "danger"), unsafe_allow_html=True)
            elif "eligible" in opt:
                st.markdown(badge("нужно уточнить у пользователя", "warning"), unsafe_allow_html=True)

    for note in result.notes:
        st.caption(f"ℹ️ {note}")


EVENT_CARD_CLASS = {
    СТАТУС_ПРОСРОЧЕНО: "overdue",
    СТАТУС_ГОРИТ: "soon",
    СТАТУС_В_ГРАФИКЕ: "ontrack",
    СТАТУС_ВЫПОЛНЕНО: "done",
}
EVENT_BADGE = {
    СТАТУС_ПРОСРОЧЕНО: ("Просрочено", "danger"),
    СТАТУС_ГОРИТ: ("Горит", "warning"),
    СТАТУС_В_ГРАФИКЕ: ("В графике", "info"),
    СТАТУС_ВЫПОЛНЕНО: ("Выполнено", "success"),
}


def render_tracker_events(events) -> None:
    st.subheader("Дедлайны и обязательства по контракту")
    st.markdown(f"**{summarize(events)}**")
    st.write("")

    for event in sorted(events, key=lambda e: (e.due_date is None, e.due_date or date.max)):
        css_class = EVENT_CARD_CLASS.get(event.status, "nodate")
        label, kind = EVENT_BADGE.get(event.status, ("Нет даты", "neutral"))
        due = event.due_date.strftime("%d.%m.%Y") if event.due_date else "дата не определена"
        days_txt = ""
        if event.days_remaining is not None:
            if event.days_remaining < 0:
                days_txt = f" · просрочка {abs(event.days_remaining)} дн."
            else:
                days_txt = f" · осталось {event.days_remaining} дн."

        st.markdown(
            f"""<div class="event-card {css_class}">
                {badge(label, kind)}
                <div style="margin-top:8px; font-weight:600;">{event.description}</div>
                <div style="color:#64748B; font-size:0.88rem; margin-top:2px;">Срок: {due}{days_txt}</div>
                <div style="margin-top:6px; font-size:0.9rem;">{event.recommendation}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.checkbox("Отметить выполненным", key=f"tracker_done_{event.event_type}")


def render_radar_card(scored, rank: int) -> None:
    t = scored.tender
    kind = "success" if scored.score >= 50 else ("warning" if scored.score >= 20 else "neutral")
    with st.container(border=True):
        title_col, price_col = st.columns([4, 1])
        with title_col:
            st.markdown(
                f"{badge(f'#{rank} · score {scored.score}', kind)} &nbsp; **{t.reestr_number}** — {t.subject}",
                unsafe_allow_html=True,
            )
        with price_col:
            if t.nmck is not None:
                st.markdown(f"<div style='text-align:right; font-size:1.3rem; font-weight:700;'>{t.nmck:,.0f} ₽</div>".replace(",", " "), unsafe_allow_html=True)
            else:
                st.markdown(badge("НМЦК не указана", "danger"), unsafe_allow_html=True)
        st.caption(
            f"{t.customer_name} · {t.region or 'регион не указан'} · {t.law}"
            + (f" · осталось {scored.days_to_deadline} дн. на подачу" if scored.days_to_deadline is not None else "")
        )
        for p in scored.positive_reasons:
            st.markdown(f"✅ {p}")
        for f in scored.red_flags:
            st.markdown(f"🚩 {f}")

        ai = assess_complexity_with_ai(t.subject)
        if ai["is_complex"]:
            st.markdown(badge("🤖 ИИ: сложная номенклатура", "warning") + f" — {ai['reason']}", unsafe_allow_html=True)
        else:
            st.markdown(badge("🤖 ИИ: типовая номенклатура", "info") + f" — {ai['reason']}", unsafe_allow_html=True)

        if t.reestr_number in st.session_state["tender_cards"]:
            st.caption(f"✓ Уже в конвейере, этап: «{st.session_state['tender_cards'][t.reestr_number].stage}»")
        elif st.button("➕ В конвейер", key=f"radar_to_pipeline_{t.reestr_number}"):
            st.session_state["tender_cards"][t.reestr_number] = new_tender_card(t.reestr_number, t.subject, t.customer_name)
            st.rerun()


def get_call_llm():
    source = st.session_state.get("llm_source", "Демо (мок)")
    if source == "YandexGPT":
        api_key = st.session_state.get("yandex_api_key", "")
        folder_id = st.session_state.get("yandex_folder_id", "")
        if not api_key or not folder_id:
            st.sidebar.warning("Укажите API-ключ и folder_id YandexGPT — пока используется демо-режим.")
            return _mock_llm, True
        from modules.integrations.yandexgpt_client import call_yandexgpt
        return partial(call_yandexgpt, api_key=api_key, folder_id=folder_id), False
    if source == "GigaChat":
        creds = st.session_state.get("gigachat_credentials", "")
        if not creds:
            st.sidebar.warning("Укажите GigaChat Authorization key — пока используется демо-режим.")
            return _mock_llm, True
        from modules.integrations.gigachat_client import call_gigachat
        verify_ssl = not st.session_state.get("gigachat_skip_ssl", False)
        return partial(call_gigachat, credentials=creds, verify_ssl_certs=verify_ssl), False
    return _mock_llm, True


# -------------------------------------------------------------------- сайдбар

with st.sidebar:
    st.header("Настройки")
    st.caption(
        "⚠️ Это публичное демо без входа по паролю. Не вводите здесь настоящие "
        "ключи, вебхуки или реквизиты компании — вводите только тестовые значения."
    )

    st.selectbox(
        "Источник ИИ для разбора документации",
        ["Демо (мок)", "YandexGPT", "GigaChat"],
        key="llm_source",
        help="Демо-режим не читает текст — возвращает заранее заданный ответ, чтобы проверить конвейер целиком без ключей.",
    )
    if st.session_state.get("llm_source") == "YandexGPT":
        st.text_input("YandexGPT API-ключ", type="password", key="yandex_api_key")
        st.text_input("YandexGPT folder_id", key="yandex_folder_id")
    elif st.session_state.get("llm_source") == "GigaChat":
        st.text_input("GigaChat Authorization key", type="password", key="gigachat_credentials")
        st.checkbox(
            "Не проверять SSL-сертификат GigaChat (быстрый тест, небезопасно)",
            key="gigachat_skip_ssl",
            help=(
                "GigaChat использует сертификат российского Минцифры, которого обычно нет в системном "
                "хранилище доверенных сертификатов — из-за этого проверка падает с ошибкой "
                "CERTIFICATE_VERIFY_FAILED. Включите это временно, чтобы проверить работу сейчас. "
                "Для постоянной работы правильнее один раз установить сертификат Минцифры в систему — "
                "тогда проверку можно оставить включённой."
            ),
        )

    st.divider()
    st.subheader("Профиль компании")
    company_name = st.text_input("Название", value="Квалитетпром (пример)")
    company_inn = st.text_input("ИНН", value="0000000000")
    is_sme = st.checkbox("Субъект МСП", value=True)
    egrul_date = st.date_input("Дата последней выписки ЕГРЮЛ/ЕГРИП", value=date(2025, 10, 1))
    egrul_max_age = st.number_input("Макс. допустимый возраст выписки, мес.", min_value=1, max_value=24, value=6)

    st.divider()
    st.subheader("Интеграция с Bitrix24")
    st.caption("Чтобы дедлайны трекера сами становились задачами и событиями календаря у ответственного.")
    st.text_input(
        "Вебхук Bitrix24",
        type="password",
        key="bitrix_webhook_url",
        placeholder="https://портал.bitrix24.ru/rest/1/xxxxxxxx/",
        help='Приложения → Разработчикам → Другое → Входящий вебхук. Права: "Задачи" и "Календарь".',
    )
    st.number_input("ID ответственного сотрудника в Bitrix24", min_value=1, value=1, key="bitrix_responsible_id")
    st.number_input("ID генерального директора в Bitrix24 (для дайджестов)", min_value=1, value=1, key="bitrix_ceo_id")

    st.divider()
    st.subheader("Модули продукта")
    modules = [
        ("🟡", "Радар тендеров", "логика готова, работает на демо-потоке — нужен токен ЕИС для реального"),
        ("✅", "Экстрактор требований", "работает (демо-режим)"),
        ("✅", "Линтер заявки", "работает"),
        ("✅", "Калькулятор цены и рисков", "работает"),
        ("✅", "Пост-контрактный трекер", "работает"),
        ("✅", "Генератор документов (бонус)", "работает — не входил в исходную стратегию"),
        ("✅", "Цена заказа (бонус)", "работает — черновой калькулятор себестоимости"),
    ]
    for icon, name, status in modules:
        st.markdown(
            f'<div class="module-pill">{icon} <b>{name}</b> — {status}</div>',
            unsafe_allow_html=True,
        )

# сохраняем настройки интеграций на диск при каждом изменении — дёшево (маленький
# JSON), зато ключи/вебхук переживут перезапуск сервера
save_settings({k: st.session_state.get(k) for k in PERSISTED_KEYS if k in st.session_state})

# ------------------------------------------------------------------- header

st.title("📋 Тендер-помощник")
st.markdown(
    '<p class="hero-caption">Радар отбирает тендеры → извлечение требований ИИ → проверка заявки на риски '
    "отклонения → расчёт антидемпинга и предварительной цены → готовые бланки для подачи → контроль сроков "
    "после победы. Все 5 модулей продукта из стратегии работают в этом демо на реальной логике "
    "(Радар — пока на демо-потоке тендеров, без токена ЕИС).</p>",
    unsafe_allow_html=True,
)
st.write("")

tab_radar, tab_pipeline, tab_extract, tab_pricing, tab_docs, tab_tracker, tab_drawings = st.tabs(
    ["🎯 Радар", "🗂 Конвейер", "📄 Разбор документации", "🧮 Цена заказа",
     "📝 Документы", "📅 После победы", "🖍 Чертежи"]
)

# --------------------------------------------------------- вкладка 0: радар

with tab_radar:
    st.caption(
        "Фильтрует и ранжирует поток извещений под вашу номенклатуру и предпочтения, "
        "подсвечивает риски (сложная номенклатура, поджатые сроки, неподходящий размер контракта). "
        "Работает на демонстрационном списке тендеров — реальный поток появится, когда будет токен ЕИС "
        "(`eis_client.py` уже готов)."
    )

    c1, c2 = st.columns(2)
    radar_okpd2 = c1.text_input("Фокус по ОКПД2 (префиксы через запятую)", value="25.", key="radar_okpd2")
    radar_regions = c2.text_input("Предпочтительные регионы (через запятую)", value="Московская область, г. Москва", key="radar_regions")

    c3, c4, c5 = st.columns(3)
    radar_min_nmck = c3.number_input("Мин. НМЦК, ₽", min_value=0, value=500_000, step=50_000, key="radar_min_nmck")
    radar_max_nmck = c4.number_input("Макс. комфортная НМЦК, ₽", min_value=0, value=4_000_000, step=100_000, key="radar_max_nmck")
    radar_min_days = c5.number_input("Мин. дней на подготовку заявки", min_value=0, value=5, key="radar_min_days")

    radar_laws = st.multiselect("Законы", ["44-ФЗ", "223-ФЗ"], default=["44-ФЗ", "223-ФЗ"], key="radar_laws")

    st.divider()
    st.subheader("🤖 Углублённый ИИ-поиск")
    st.caption(
        "Опишите обычными словами, что ищете — ИИ сам решит, подходит ли закупка по смыслу, "
        "даже если точных ключевых слов в тексте нет. Проще, чем настраивать профили ниже, но "
        "менее предсказуемо — используйте то, что удобнее, можно оба сразу."
    )
    radar_ai_query = st.text_input(
        "Что ищете?",
        value="",
        key="radar_ai_query",
        placeholder="например: измерительный инструмент для контроля диаметра деталей",
    )

    st.divider()
    st.subheader("Профили поиска (плюс/минус-слова)")
    st.caption(
        "Решает проблему омонимов вроде «скобы измерительные» vs «скобы для степлера»: обязательные слова "
        "должны быть все, подтверждающие — хотя бы одно (иначе спорный случай уйдёт на проверку ИИ), "
        "слова-исключения сразу отсекают явно не то."
    )
    n_profiles = st.number_input("Сколько профилей поиска", min_value=0, max_value=5, value=1, key="radar_n_profiles")
    keyword_profiles: list[KeywordProfile] = []
    for i in range(int(n_profiles)):
        with st.container(border=True):
            pn1, pn2 = st.columns([1, 3])
            profile_name = pn1.text_input("Название профиля", value="Скобы измерительные" if i == 0 else f"Профиль {i + 1}", key=f"radar_kp_name_{i}")
            pc1, pc2, pc3 = st.columns(3)
            default_must = "скоб" if i == 0 else ""
            default_confirm = "измерительн, штангенциркул, калибр, гост 166" if i == 0 else ""
            default_exclude = "степлер, канцеляр, зубн, брекет, ортодонт" if i == 0 else ""
            must_raw = pc1.text_input("Обязательные слова (через запятую)", value=default_must, key=f"radar_kp_must_{i}")
            confirm_raw = pc2.text_input("Слова-подтверждения (любое из)", value=default_confirm, key=f"radar_kp_confirm_{i}")
            exclude_raw = pc3.text_input("Слова-исключения", value=default_exclude, key=f"radar_kp_exclude_{i}")
            keyword_profiles.append(KeywordProfile(
                name=profile_name,
                must_include=[w.strip() for w in must_raw.split(",") if w.strip()],
                confirm_any=[w.strip() for w in confirm_raw.split(",") if w.strip()],
                exclude=[w.strip() for w in exclude_raw.split(",") if w.strip()],
            ))

    radar_prefs = RadarPreferences(
        okpd2_focus=[c.strip() for c in radar_okpd2.split(",") if c.strip()],
        preferred_regions=[r.strip() for r in radar_regions.split(",") if r.strip()],
        min_nmck=radar_min_nmck,
        max_nmck=radar_max_nmck or None,
        min_days_to_deadline=radar_min_days,
        laws=radar_laws or ["44-ФЗ", "223-ФЗ"],
        keyword_profiles=keyword_profiles,
        ai_search_query=radar_ai_query,
    )

    st.divider()
    ranked = rank_tenders(demo_tenders(), radar_prefs)
    st.subheader(f"Ранжированный список ({len(ranked)} тендеров)")
    for i, scored in enumerate(ranked, start=1):
        render_radar_card(scored, i)

# ------------------------------------------------------- вкладка: конвейер

with tab_pipeline:
    st.caption(
        "Путь одного тендера от обнаружения до готовой заявки в три этапа: рассмотрение → принятие решения "
        "по цене и участию → подготовка документов. Карточки добавляются кнопкой «➕ В конвейер» на вкладке "
        "«Радар» или вручную ниже."
    )

    with st.expander("➕ Добавить карточку вручную"):
        pc1, pc2, pc3 = st.columns(3)
        new_reestr = pc1.text_input("Реестровый номер", key="pipe_new_reestr")
        new_subject = pc2.text_input("Предмет закупки", key="pipe_new_subject")
        new_customer = pc3.text_input("Заказчик", key="pipe_new_customer")
        if st.button("Добавить →", key="pipe_add_manual"):
            if new_reestr.strip():
                st.session_state["tender_cards"][new_reestr.strip()] = new_tender_card(new_reestr.strip(), new_subject.strip(), new_customer.strip())
                st.success(f"Добавлено: {new_reestr.strip()}")
            else:
                st.error("Укажите реестровый номер.")

    st.divider()
    pipeline_cards = st.session_state["tender_cards"]
    active_cards = [c for c in pipeline_cards.values() if c.stage in ЭТАПЫ_ПОРЯДОК]

    if not active_cards:
        st.info("Пока нет ни одной карточки в работе — добавьте с вкладки «Радар» или вручную выше.")
    else:
        stage_cols = st.columns(len(ЭТАПЫ_ПОРЯДОК))
        for col, stage in zip(stage_cols, ЭТАПЫ_ПОРЯДОК):
            with col:
                st.markdown(f"**{stage}**")
                stage_cards = [c for c in active_cards if c.stage == stage]
                if not stage_cards:
                    st.caption("Пусто")
                for card in stage_cards:
                    with st.container(border=True):
                        st.markdown(f"**{card.reestr_number}**")
                        st.caption(f"{card.subject or '—'} · {card.customer_name or '—'}")
                        card.decision_note = st.text_area(
                            "Заметка", value=card.decision_note, key=f"pipe_note_{card.reestr_number}",
                            height=68, placeholder="Заметка по цене/участию",
                        )

                        if stage == ЭТАП_РЕШЕНИЕ:
                            nc1, nc2 = st.columns(2)
                            card_nmck = nc1.number_input("НМЦК, ₽", min_value=0, value=0, step=100_000, key=f"pipe_nmck_{card.reestr_number}")
                            card_price = nc2.number_input("Цена, ₽", min_value=0, value=0, step=100_000, key=f"pipe_price_{card.reestr_number}")
                            if st.button("📨 Дайджест ГД →", key=f"pipe_digest_{card.reestr_number}"):
                                webhook = st.session_state.get("bitrix_webhook_url", "")
                                ceo_id = st.session_state.get("bitrix_ceo_id")
                                if not webhook:
                                    st.error("Укажите вебхук Bitrix24 в настройках слева.")
                                else:
                                    try:
                                        push_executive_digest(
                                            webhook, ceo_id, card.reestr_number, card.subject,
                                            nmck=card_nmck or None, proposed_price=card_price or None,
                                            contract_draft_summary=card.decision_note,
                                        )
                                        st.success("Дайджест отправлен в Bitrix24.")
                                    except Exception as e:
                                        st.error(f"Не удалось отправить: {e}")

                        if stage == ЭТАП_ДОКУМЕНТЫ:
                            if st.button("📄 К разбору документации →", key=f"pipe_to_extract_{card.reestr_number}", type="primary"):
                                st.session_state["queued_reestr"] = card.reestr_number
                                st.session_state["queued_customer"] = card.customer_name
                                st.session_state["queued_subject"] = card.subject
                                st.session_state["queued_document_text"] = demo_documentation_text(card.reestr_number)
                                st.success("Данные переданы — откройте вкладку «📄 Разбор документации», всё уже там.")

                        bc1, bc2 = st.columns(2)
                        if bc1.button("→ Далее", key=f"pipe_advance_{card.reestr_number}"):
                            card.advance(note=card.decision_note)
                            st.rerun()
                        if bc2.button("✕ Отклонить", key=f"pipe_reject_{card.reestr_number}"):
                            card.reject(card.decision_note or "причина не указана")
                            st.rerun()

    rejected_cards = [c for c in pipeline_cards.values() if c.rejected]
    if rejected_cards:
        st.divider()
        with st.expander(f"Отклонено ({len(rejected_cards)})"):
            for card in rejected_cards:
                st.write(f"**{card.reestr_number}** — {card.subject or '—'}")
                st.caption(f"Причина: {card.rejection_reason}")

# -------------------------------------------------------- вкладка 1: разбор

with tab_extract:
    if st.session_state.get("queued_reestr"):
        st.info(f"📌 Пришло из Конвейера: закупка № {st.session_state['queued_reestr']} — номер уже подставлен ниже.")
        if st.session_state.get("queued_document_text"):
            # тендер из демо-набора Радара — для него есть полный демо-текст документации
            # (demo_documentation_text в tender_radar.py), подставляем по-настоящему, а не
            # только предмет закупки одной строкой
            sync_default("extract_document_text", st.session_state["queued_document_text"])
        elif st.session_state.get("queued_subject"):
            # тендер добавлен в Конвейер вручную (не из демо-набора Радара) — полного текста
            # неоткуда взять без токена ЕИС/API агрегатора, честно подставляем заглушку вместо
            # того чтобы молча оставлять пусто/демо-текст, будто ничего не передалось
            placeholder_text = (
                "[Это только краткий предмет закупки — НЕ полная документация. "
                "Настоящего текста документации взять неоткуда без токена ЕИС или API агрегатора. "
                "Вставьте текст сами или загрузите файл документации ниже — иначе разбор будет "
                "неточным, ИИ увидит только эту одну строку.]\n\n"
                + st.session_state["queued_subject"]
            )
            sync_default("extract_document_text", placeholder_text)

    sync_default("reestr_number", st.session_state.get("queued_reestr") or "ДЕМО-0000000000000000000")
    reestr_number = st.text_input("Реестровый номер закупки", key="reestr_number")

    uploaded_doc = st.file_uploader(
        "Загрузить файл документации (PDF/DOCX/TXT) — текст достанется сам",
        type=["pdf", "docx", "txt"],
        key="extract_file_upload",
    )
    if uploaded_doc is not None:
        try:
            extracted_text = extract_text_from_upload(uploaded_doc.name, uploaded_doc.getvalue())
            if extracted_text:
                st.session_state["extract_document_text"] = extracted_text
                st.caption(f"✅ Текст извлечён из файла ({len(extracted_text)} символов) — можно проверить и поправить ниже.")
            else:
                st.warning(
                    "Файл загрузился, но текста в нём не нашлось — похоже, это скан-картинка без текстового слоя. "
                    "Вставьте текст вручную ниже."
                )
        except ValueError as e:
            st.error(str(e))

    document_text = st.text_area(
        "Текст документации закупки",
        value=st.session_state.get("extract_document_text", DEMO_TEXT),
        height=200,
        key="extract_document_text",
    )
    run_extract = st.button("Разобрать документацию →", type="primary")

    if run_extract:
        call_llm, is_mock = get_call_llm()
        with st.spinner("Разбираю документацию..."):
            try:
                reqs = extract_requirements(reestr_number, document_text, call_llm)
                st.session_state["reqs"] = reqs
            except Exception as e:
                st.error(f"Не удалось разобрать ответ модели: {e}")

    if "reqs" in st.session_state:
        st.divider()
        render_requirements(st.session_state["reqs"])

        st.divider()
        st.subheader("Данные о сборке конкретной заявки")
        st.caption("Это факты про то, как заявка собрана именно сейчас — их не может знать ИИ, только вы.")

        company = CompanyProfile(
            name=company_name,
            inn=company_inn,
            is_sme=is_sme,
            egrul_extract_date=egrul_date,
            egrul_max_age_months_allowed_default=egrul_max_age,
        )
        base_answers = answers_from_requirements(st.session_state["reqs"], company)

        cols = st.columns(len(APPLICATION_FIELDS))
        for col, (field_id, label, default) in zip(cols, APPLICATION_FIELDS):
            base_answers[field_id] = col.checkbox(label, value=default, key=f"pipeline_{field_id}")

        c1, c2 = st.columns(2)
        base_answers["security_amount_paid"] = c1.number_input(
            "Фактически перечислено обеспечение заявки, ₽",
            min_value=0,
            value=int(st.session_state["reqs"].application_security_amount or 0),
        )
        base_answers["using_bank_guarantee"] = c2.checkbox("Используется банковская гарантия (вместо денег на спецсчёте)", value=False)
        if base_answers["using_bank_guarantee"]:
            base_answers["guarantee_matches_44fz_requirements"] = st.checkbox(
                "Гарантия соответствует требованиям ст. 45 44-ФЗ", value=True
            )

        if st.button("Проверить заявку на риски →", type="primary"):
            render_risks(run_checklist(base_answers))

        st.info("➡️ **Дальше:** вкладка «🧮 Цена заказа» — посчитать цену, или сразу «📝 Документы» — собрать бланки.")

    st.divider()
    with st.expander("✅ Линтер вручную — если документацию ещё не разбирали"):
        st.caption("Прогнать базовый чек-лист рисков без разбора документации — если ответы на вопросы уже известны.")
        answers = {}
        cols = st.columns(2)
        for i, (field_id, label, default) in enumerate(APPLICATION_FIELDS):
            answers[field_id] = cols[i % 2].checkbox(label, value=default, key=f"solo_{field_id}")

        c1, c2, c3 = st.columns(3)
        answers["security_amount_required"] = c1.number_input("Требуемое обеспечение заявки, ₽", min_value=0, value=50000)
        answers["security_amount_paid"] = c2.number_input("Фактически перечислено, ₽", min_value=0, value=50000)
        answers["egrul_age_months"] = c3.number_input("Возраст выписки ЕГРЮЛ, мес.", min_value=0, value=3)
        answers["egrul_max_age_months_allowed"] = 6

        answers["using_bank_guarantee"] = st.checkbox("Используется банковская гарантия", value=False, key="solo_bg")
        if answers["using_bank_guarantee"]:
            answers["guarantee_matches_44fz_requirements"] = st.checkbox(
                "Гарантия соответствует ст. 45 44-ФЗ", value=True, key="solo_bg_ok"
            )

        if st.button("Проверить →", type="primary", key="solo_run"):
            render_risks(run_checklist(answers))

        with st.expander("Полный список проверок в линтере"):
            for item in CHECKLIST:
                st.write(f"**[{item.stage}]** {item.risk}")

# ------------------------------------------------------ вкладка 3: антидемпинг


# ------------------------------------------------------- вкладка: цена заказа

with tab_pricing:
    st.caption(
        "Черновой расчёт: себестоимость по статьям затрат + целевая наценка = предварительная цена. "
        "Пока данные вводятся вручную — когда появится внутреннее приложение с реальной себестоимостью "
        "номенклатуры, эти поля можно будет заполнять оттуда автоматически."
    )

    reqs_for_pricing = st.session_state.get("reqs")

    def _run_ai_price_estimate():
        context = build_digest(reqs_for_pricing) if reqs_for_pricing else "Данных о требованиях тендера пока нет — общая оценка."
        security = reqs_for_pricing.contract_security_amount if reqs_for_pricing else None
        call_llm, _ = get_call_llm()
        ai_items = estimate_cost_items_with_ai(context, security_amount=security, call_llm=call_llm)
        st.session_state["price_n_items"] = len(ai_items)
        for i, item in enumerate(ai_items):
            st.session_state[f"price_item_name_{i}"] = item.name
            st.session_state[f"price_item_amount_{i}"] = int(item.amount)

    # автозапуск: как только на вкладке "Разбор документации" появились новые
    # требования тендера, черновая оценка сама подставляется здесь — не нужно
    # нажимать кнопку; срабатывает один раз на новый reqs, а не на каждый rerun,
    # иначе стирало бы то, что сами поправили руками
    reqs_signature = reqs_for_pricing.reestr_number if reqs_for_pricing else None
    if reqs_signature and st.session_state.get("_last_ai_priced_reestr") != reqs_signature:
        st.session_state["_last_ai_priced_reestr"] = reqs_signature
        _run_ai_price_estimate()
        st.info(
            "🤖 Черновая оценка ИИ подставлена автоматически по данным разбора документации — это грубая "
            "прикидка по масштабу сделки, не точный расчёт. Поправьте цифры под реальные, когда появятся."
        )

    if st.button("🤖 Прикинуть через ИИ заново →", key="price_ai_estimate"):
        _run_ai_price_estimate()
        st.info(
            "Черновая оценка ИИ подставлена ниже — это грубая прикидка по масштабу сделки, не точный расчёт. "
            "Поправьте цифры под реальные, когда появятся."
        )

    n_cost_items = st.number_input("Сколько статей затрат", min_value=1, max_value=10, value=3, key="price_n_items")
    cost_items: list[CostItem] = []
    for i in range(int(n_cost_items)):
        pc1, pc2 = st.columns([2, 1])
        default_names = ["Материалы", "Работы (изготовление)", "Накладные расходы"]
        default_name = default_names[i] if i < len(default_names) else f"Статья {i + 1}"
        item_name = pc1.text_input("Статья затрат", value=default_name, key=f"price_item_name_{i}")
        item_amount = pc2.number_input("Сумма, ₽", min_value=0, value=0, step=10_000, key=f"price_item_amount_{i}")
        cost_items.append(CostItem(item_name, item_amount))

    st.divider()
    pc3, pc4 = st.columns(2)
    margin_percent = pc3.number_input("Целевая наценка, %", min_value=0.0, value=15.0, step=1.0, key="price_margin")
    price_nmck = pc4.number_input("НМЦК закупки, ₽ (0, если неизвестна)", min_value=0, value=0, step=100_000, key="price_nmck")

    estimate = None
    try:
        estimate = calculate_price(cost_items, margin_percent, price_nmck or None)
        st.session_state["last_estimated_price"] = estimate.suggested_price
        st.divider()
        st.subheader("Результат")
        pc5, pc6, pc7 = st.columns(3)
        pc5.metric("Себестоимость", f"{estimate.total_cost:,.0f} ₽".replace(",", " "))
        pc6.metric("Наценка", f"{estimate.margin_percent:.0f}%")
        pc7.metric("Предварительная цена", f"{estimate.suggested_price:,.0f} ₽".replace(",", " "))

        if estimate.discount_vs_nmck_percent is not None:
            st.caption(f"Снижение относительно НМЦК: {estimate.discount_vs_nmck_percent:.1f}%")
        if estimate.antidemping_warning:
            st.warning(estimate.antidemping_warning)
        elif estimate.nmck:
            st.success("Антидемпинговые меры при этой цене не включаются.")
        st.info("➡️ **Дальше:** вкладка «📝 Документы» — собрать бланки для подачи.")
    except ValueError as e:
        st.error(str(e))

    st.divider()
    with st.expander("🔍 Подробный расчёт по ст. 37 44-ФЗ (обеспечение, аванс)"):
        st.caption(
            "Если антидемпинг сработал выше — здесь можно посчитать точную сумму требуемого обеспечения "
            "и узнать, выплатят ли аванс."
        )
        default_detailed_nmck = int(price_nmck) if price_nmck else 6_000_000
        default_detailed_price = int(estimate.suggested_price) if estimate else int(default_detailed_nmck * 0.72)

        ac1, ac2 = st.columns(2)
        detailed_nmck = ac1.number_input("НМЦК, ₽", min_value=1, value=default_detailed_nmck, step=100_000, key="detail_nmck")
        detailed_security = ac2.number_input("Обеспечение по извещению, ₽", min_value=0, value=300_000, step=10_000, key="detail_security")

        ac3, ac4 = st.columns(2)
        detailed_price = ac3.number_input("Предложенная цена, ₽", min_value=0, value=default_detailed_price, step=100_000, key="detail_price")
        detailed_advance = ac4.number_input("Сумма аванса по документации, ₽ (0, если не предусмотрен)", min_value=0, value=0, step=10_000, key="detail_advance")

        good_faith = st.selectbox(
            "Есть 3 контракта за последние 3 года без неустоек (один ≥ 20% от текущего НМЦК)?",
            ["Не знаю / уточню позже", "Да", "Нет"],
            key="detail_good_faith",
        )
        good_faith_map = {"Не знаю / уточню позже": None, "Да": True, "Нет": False}

        if st.button("Посчитать подробно →", type="primary"):
            try:
                result = calculate_antidemping(
                    nmck=detailed_nmck,
                    notice_security_amount=detailed_security,
                    proposed_price=detailed_price,
                    advance_amount=detailed_advance,
                    has_three_qualifying_contracts=good_faith_map[good_faith],
                )
                st.divider()
                render_antidemping(result)
            except ValueError as e:
                st.error(str(e))

# ------------------------------------------------------ вкладка 4: документы

with tab_docs:
    st.warning(
        "⚠️ Это шаблоны, а не юридическая консультация: проверьте и подпишите документы сами "
        "перед подачей. Декларации по ст. 31 44-ФЗ и о статусе СМП на большинстве электронных "
        "площадок формируются автоматически при подаче заявки — прикладывайте эти файлы отдельно, "
        "только если закупка не электронная или документация прямо требует отдельный файл."
    )

    reqs_for_docs = st.session_state.get("reqs")
    tracker_contract = st.session_state.get("tracker_contract")

    if reqs_for_docs and reqs_for_docs.required_documents:
        matched = match_required_documents(reqs_for_docs.required_documents)
        auto_names = [m["required"] for m in matched if m["auto_generatable"]]
        manual_names = [m["required"] for m in matched if not m["auto_generatable"]]
        with st.container(border=True):
            st.markdown("**Что требует именно эта закупка** (из вкладки «Разбор документации»)")
            if auto_names:
                st.markdown("✅ Можем сгенерировать здесь: " + ", ".join(auto_names))
            if manual_names:
                st.markdown("📎 Нужно приложить готовым файлом (шаблона нет — это не типовой бланк): " + ", ".join(manual_names))

    st.subheader("Реквизиты для документов")

    c1, c2 = st.columns(2)
    default_doc_reestr = (reqs_for_docs.reestr_number if reqs_for_docs else None) or st.session_state.get("queued_reestr") or "ДЕМО-0000000000000000000"
    sync_default("doc_reestr", default_doc_reestr)
    doc_reestr = c1.text_input("Реестровый номер закупки", key="doc_reestr")
    default_doc_customer = st.session_state.get("queued_customer") or (tracker_contract.customer_name if tracker_contract else "")
    sync_default("doc_customer", default_doc_customer)
    doc_customer = c2.text_input("Заказчик", key="doc_customer")

    c3, c4 = st.columns(2)
    supplier_ogrn = c3.text_input("ОГРН", value="0000000000000", key="doc_ogrn")
    supplier_address = c4.text_input("Юридический адрес", value="", key="doc_address")

    c5, c6 = st.columns(2)
    director_name = c5.text_input("ФИО руководителя", value="", key="doc_director_name")
    director_position = c6.text_input("Должность руководителя", value="Генеральный директор", key="doc_director_position")

    c7, c8 = st.columns(2)
    legal_form = c7.selectbox(
        "Организационная форма",
        [ФОРМА_ООО_ЕДИНСТВЕННЫЙ_УЧАСТНИК, ФОРМА_ООО_НЕСКОЛЬКО_УЧАСТНИКОВ, ФОРМА_ИП],
        key="doc_legal_form",
    )
    balance_assets = c8.number_input(
        "Балансовая стоимость активов, ₽ (для расчёта крупной сделки)",
        min_value=0, value=0, step=100_000, key="doc_balance_assets",
        help="Данные годовой бухгалтерской отчётности. Если не заполнить — приложение не сможет определить, крупная ли сделка, и предупредит об этом в справке.",
    )

    st.divider()
    st.subheader("Параметры сделки")
    default_deal_amount = int(tracker_contract.contract_price) if tracker_contract and tracker_contract.contract_price else 1_200_000
    c9, c10 = st.columns(2)
    deal_amount = c9.number_input("Сумма сделки (цена контракта), ₽", min_value=0, value=default_deal_amount, key="doc_deal_amount")
    deal_subject = c10.text_input("Предмет сделки", value="поставка товара по контракту", key="doc_deal_subject")

    c11, c12 = st.columns(2)
    doc_city = c11.text_input("Город", value="Москва", key="doc_city")
    doc_date_value = c12.date_input("Дата документов", value=date.today(), key="doc_date")

    st.divider()
    st.subheader("Какие документы сгенерировать")
    c13, c14, c15, c16, c17 = st.columns(5)
    want_31fz = c13.checkbox("Декларация ст. 31", value=True, key="doc_want_31fz")
    want_sme = c14.checkbox("Декларация СМП", value=is_sme, key="doc_want_sme")
    want_major = c15.checkbox("Крупная сделка", value=True, key="doc_want_major")
    want_cover = c16.checkbox("Сопровод. письмо", value=True, key="doc_want_cover")
    want_disagreement = c17.checkbox("Протокол разногласий", value=False, key="doc_want_disagreement")

    disagreement_items: list[DisagreementItem] = []
    if want_disagreement:
        st.caption(
            "Нужен, только если заказчик уже прислал проект контракта и в нём есть пункты, "
            "не совпадающие с извещением/документацией/вашей заявкой — подаётся через ЭТП "
            "в течение 5 рабочих дней после получения проекта контракта."
        )
        n_items = st.number_input("Сколько спорных пунктов", min_value=1, max_value=5, value=1, key="doc_dis_count")
        for i in range(int(n_items)):
            with st.container(border=True):
                st.markdown(f"**Пункт разногласий {i + 1}**")
                dc1, dc2 = st.columns(2)
                clause = dc1.text_input("Пункт проекта контракта", value="", key=f"dis_clause_{i}", placeholder="например, п. 4.2")
                customer_wording = dc2.text_input("Редакция заказчика", value="", key=f"dis_customer_{i}")
                dc3, dc4 = st.columns(2)
                supplier_wording = dc3.text_input("Ваша редакция", value="", key=f"dis_supplier_{i}")
                justification = dc4.text_input("Обоснование (ссылка на извещение/документацию/заявку)", value="", key=f"dis_just_{i}")
                disagreement_items.append(DisagreementItem(clause, customer_wording, supplier_wording, justification))

    if st.button("Сгенерировать документы →", type="primary"):
        supplier = SupplierDetails(
            name=company_name,
            inn=company_inn,
            ogrn=supplier_ogrn,
            address=supplier_address,
            director_name=director_name,
            director_position=director_position,
            legal_form=legal_form,
            balance_sheet_assets=balance_assets,
        )

        generated: list[tuple[str, bytes]] = []

        if want_31fz:
            data = to_bytes(generate_declaration_31fz(supplier, doc_reestr, doc_date_value))
            generated.append(("Декларация ст. 31 44-ФЗ.docx", data))
        if want_sme:
            data = to_bytes(generate_sme_declaration(supplier, doc_reestr, doc_date_value))
            generated.append(("Декларация СМП.docx", data))
        if want_major:
            major_doc, major_label = generate_major_transaction_document(
                supplier, doc_reestr, deal_amount, deal_subject, doc_city, doc_date_value,
            )
            data = to_bytes(major_doc)
            generated.append((f"{major_label}.docx", data))
        if want_cover:
            docs_list = reqs_for_docs.required_documents if reqs_for_docs else []
            data = to_bytes(generate_cover_letter(supplier, doc_reestr, doc_customer, docs_list, doc_city, doc_date_value))
            generated.append(("Сопроводительное письмо.docx", data))
        if want_disagreement:
            data = to_bytes(generate_disagreement_protocol(supplier, doc_reestr, doc_customer, disagreement_items, doc_date_value))
            generated.append(("Протокол разногласий.docx", data))

        st.session_state["generated_docs"] = generated

    if st.session_state.get("generated_docs"):
        st.divider()
        st.subheader("Готовые файлы")
        docs_generated = st.session_state["generated_docs"]

        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            for filename, data in docs_generated:
                zf.writestr(filename, data)
        st.download_button(
            "📦 Скачать всё архивом (.zip)",
            data=zip_buf.getvalue(),
            file_name=f"документы_{doc_reestr}.zip",
            mime="application/zip",
            type="primary",
        )

        cols = st.columns(len(docs_generated))
        for col, (filename, data) in zip(cols, docs_generated):
            col.download_button(f"📄 {filename}", data=data, file_name=filename, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

        st.info("➡️ **Дальше:** заявку подали. Если выиграли тендер — вкладка «📅 После победы» для контроля сроков.")

# ------------------------------------------------------ вкладка 5: после победы

with tab_tracker:
    st.caption(
        "После победы в тендере легко потерять из виду дедлайны среди текучки — модуль считает даты "
        "и подсвечивает, что горит прямо сейчас."
    )
    reqs_for_tracker = st.session_state.get("reqs")

    c1, c2 = st.columns(2)
    default_tr_reestr = (reqs_for_tracker.reestr_number if reqs_for_tracker else None) or st.session_state.get("queued_reestr") or "ДЕМО-0000000000000000000"
    sync_default("tr_reestr", default_tr_reestr)
    contract_reestr = c1.text_input("Реестровый номер контракта", key="tr_reestr")
    default_tr_customer = st.session_state.get("queued_customer") or "ДЕМО Заказчик (пример)"
    sync_default("tr_customer", default_tr_customer)
    contract_customer = c2.text_input("Заказчик", key="tr_customer")

    c3, c4 = st.columns(2)
    default_tr_price = int(st.session_state.get("last_estimated_price") or 1_200_000)
    sync_default("tr_price", default_tr_price)
    contract_price = c3.number_input("Цена контракта, ₽", min_value=0, step=10_000, key="tr_price")
    signing_date = c4.date_input("Дата подписания контракта", value=date.today() - timedelta(days=40), key="tr_signing")

    c5, c6 = st.columns(2)
    default_delivery = reqs_for_tracker.delivery_deadline if reqs_for_tracker and reqs_for_tracker.delivery_deadline else date.today() + timedelta(days=20)
    sync_default("tr_delivery", default_delivery)
    delivery_deadline = c5.date_input("Срок поставки", key="tr_delivery")
    default_warranty = reqs_for_tracker.warranty_period_months if reqs_for_tracker and reqs_for_tracker.warranty_period_months else 12
    sync_default("tr_warranty", default_warranty)
    warranty_months = c6.number_input("Гарантийный срок, мес.", min_value=0, key="tr_warranty")

    c7, c8 = st.columns(2)
    default_sec_amount = int(reqs_for_tracker.contract_security_amount) if reqs_for_tracker and reqs_for_tracker.contract_security_amount else 180_000
    sync_default("tr_sec_amount", default_sec_amount)
    security_amount = c7.number_input("Сумма обеспечения контракта, ₽", min_value=0, key="tr_sec_amount")
    security_type = c8.selectbox(
        "Способ обеспечения",
        [ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ, ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ],
        format_func=lambda v: "Деньги на спецсчёте" if v == ОБЕСПЕЧЕНИЕ_ДЕНЬГАМИ else "Банковская гарантия",
        key="tr_sec_type",
    )

    security_expiry = None
    if security_type == ОБЕСПЕЧЕНИЕ_ГАРАНТИЕЙ:
        security_expiry = st.date_input("Срок действия банковской гарантии", value=date.today() + timedelta(days=5), key="tr_sec_expiry")

    completed_events = {
        et for et in [СОБЫТИЕ_ПОСТАВКА, СОБЫТИЕ_ЗАКРЫВАЮЩИЕ_ДОКУМЕНТЫ, СОБЫТИЕ_ГАРАНТИЯ, СОБЫТИЕ_ОБЕСПЕЧЕНИЕ]
        if st.session_state.get(f"tracker_done_{et}", False)
    }
    contract = build_contract_from_requirements(
        reestr_number=contract_reestr,
        customer_name=contract_customer,
        contract_price=contract_price,
        signing_date=signing_date,
        delivery_deadline=delivery_deadline,
        warranty_period_months=warranty_months,
        security_amount=security_amount,
        security_type=security_type,
        security_expiry_date=security_expiry,
    )
    contract.completed_events = completed_events
    events = get_tracked_events(contract)

    st.divider()
    render_tracker_events(events)

    st.divider()
    st.subheader("Отправить дедлайны из этого контракта")
    contract_label = f"{contract.reestr_number} / {contract.customer_name}"

    col_ics, col_bx = st.columns(2)

    with col_ics:
        st.markdown("**Экспорт в личный календарь**")
        st.caption("Без интеграций и аккаунтов — работает всегда, независимо от Bitrix24.")
        st.download_button(
            "📅 Скачать .ics",
            data=build_ics(events, contract_label),
            file_name=f"deadlines_{contract.reestr_number}.ics",
            mime="text/calendar",
        )

    with col_bx:
        st.markdown("**Задачи и события в Bitrix24**")
        create_tasks = st.checkbox("Создавать задачи", value=True, key="bx_tasks")
        create_cal = st.checkbox("Создавать события календаря", value=True, key="bx_cal")
        if st.button("🔗 Отправить в Bitrix24 →", type="primary"):
            webhook = st.session_state.get("bitrix_webhook_url", "")
            responsible = st.session_state.get("bitrix_responsible_id")
            if not webhook:
                st.error("Сначала укажите вебхук Bitrix24 в настройках слева.")
            else:
                with st.spinner("Отправляю в Bitrix24..."):
                    try:
                        push_results = push_tracked_events(
                            webhook, responsible, events, contract_label,
                            create_tasks=create_tasks, create_calendar_events=create_cal,
                        )
                    except Exception as e:
                        st.error(f"Не удалось подключиться к Bitrix24: {e}")
                        push_results = None

                if push_results is not None:
                    if not push_results:
                        st.info("Нет дедлайнов для отправки — все уже выполнены или без даты.")
                    else:
                        ok_count = sum(1 for r in push_results if not r["errors"])
                        st.success(f"Отправлено без ошибок: {ok_count} из {len(push_results)}")
                        for r in push_results:
                            if r["errors"]:
                                st.warning(f"{r['event']}: " + "; ".join(r["errors"]))
                            else:
                                st.caption(f"✅ {r['event']}")

# ------------------------------------------------- вкладка: обезличивание чертежей

with tab_drawings:
    st.caption(
        "Загрузите скан чертежа → закрасьте на нём чувствительные зоны (номера, заказчика, штамп) прямо "
        "мышкой → скачайте обезличенную версию. Отдельно — реестр соответствий «оригинал ↔ наш код», "
        "который не привязан к конкретному чертежу и копится по всем закупкам."
    )
    st.warning(
        "⚠️ Это публичное демо — загруженный файл до закраски уходит на чужой сервер (Streamlit Cloud). "
        "Не загружайте сюда настоящие чертежи заказчика, только тестовые/учебные файлы."
    )

    st.subheader("Закраска чертежа")
    uploaded = st.file_uploader("Скан чертежа (PNG/JPG/BMP/TIFF)", type=["png", "jpg", "jpeg", "bmp", "tiff"], key="draw_upload")

    if uploaded is not None:
        original_image = Image.open(uploaded)
        orig_w, orig_h = original_image.size

        max_display_width = 700
        scale = min(1.0, max_display_width / orig_w)
        display_w, display_h = int(orig_w * scale), int(orig_h * scale)
        display_image = original_image.resize((display_w, display_h)) if scale < 1.0 else original_image

        st.caption(f"Размер оригинала: {orig_w}×{orig_h}px.")

        def _run_auto_redact():
            try:
                with st.spinner("Ищу текст и закрашиваю (при первом запуске скачиваются модели, может занять минуту)..."):
                    suggestions = suggest_text_regions_ocr(original_image)
                    pad = 4  # небольшой запас вокруг найденного текста, чтобы не обрезать край буквы
                    boxes = [
                        (max(0, s.box[0] - pad), max(0, s.box[1] - pad), s.box[2] + pad, s.box[3] + pad)
                        for s in suggestions
                    ]
                    st.session_state["ocr_suggestions"] = suggestions
                    if boxes:
                        st.session_state["redacted_image"] = redact_image(original_image, boxes)
                    else:
                        st.warning("OCR не нашёл текста на изображении — попробуйте закрасить вручную ниже.")
            except ImportError as e:
                st.error(str(e))

        # автоматически обезличиваем сразу при загрузке нового файла — не нужно
        # жать кнопку самим; срабатывает один раз на файл (по имени+размеру), а
        # не на каждый rerun, иначе стирало бы ручные правки на холсте ниже
        file_signature = f"{uploaded.name}:{uploaded.size}"
        if st.session_state.get("_last_auto_redacted_file") != file_signature:
            st.session_state["_last_auto_redacted_file"] = file_signature
            _run_auto_redact()

        auto_col, hint_col = st.columns(2)
        with auto_col:
            if st.button("⚡ Обезличить заново (ИИ)", key="draw_ocr_auto"):
                _run_auto_redact()
        with hint_col:
            st.caption(
                "Обезличивается автоматически при загрузке файла. Кнопка — чтобы прогнать ИИ ещё раз (например, "
                "после ручных правок на холсте). Проверьте результат: ИИ может пропустить рукописный текст или, "
                "наоборот, закрасить лишнее — дорисуйте/сотрите вручную на холсте ниже, если нужно."
            )

        if st.session_state.get("ocr_suggestions"):
            suggestions = st.session_state["ocr_suggestions"]
            with st.expander(f"Что распознал OCR ({len(suggestions)} областей)"):
                st.image(draw_suggestion_overlay(original_image, suggestions), width="stretch")
                for s in suggestions:
                    st.caption(f"«{s.text}» (уверенность {s.confidence:.0%}) — область {s.box}")

        st.divider()
        st.caption("Ручная правка (дорисовать/поправить то, что нашёл ИИ, или закрасить с нуля):")
        canvas_result = st_canvas(
            fill_color="rgba(0, 0, 0, 1)",
            stroke_width=1,
            stroke_color="#000000",
            background_image=display_image,
            height=display_h,
            width=display_w,
            drawing_mode="rect",
            key="draw_canvas",
        )

        rectangles_original_scale: list[tuple[int, int, int, int]] = []
        if canvas_result.json_data is not None:
            for obj in canvas_result.json_data.get("objects", []):
                left = obj.get("left", 0)
                top = obj.get("top", 0)
                width = obj.get("width", 0) * obj.get("scaleX", 1)
                height = obj.get("height", 0) * obj.get("scaleY", 1)
                x1, y1 = left / scale, top / scale
                x2, y2 = (left + width) / scale, (top + height) / scale
                rectangles_original_scale.append((int(x1), int(y1), int(x2), int(y2)))

        if rectangles_original_scale:
            st.caption(f"Отмечено областей для закраски: {len(rectangles_original_scale)}")
            if st.button("Применить обезличивание →", type="primary"):
                redacted = redact_image(original_image, rectangles_original_scale)
                st.session_state["redacted_image"] = redacted

        if "redacted_image" in st.session_state:
            st.divider()
            st.subheader("Результат")
            st.image(st.session_state["redacted_image"], caption="Обезличенный чертёж", width="stretch")
            buf = BytesIO()
            st.session_state["redacted_image"].save(buf, format="PNG")
            st.download_button(
                "📥 Скачать обезличенный чертёж (.png)",
                data=buf.getvalue(),
                file_name=f"обезличено_{uploaded.name.rsplit('.', 1)[0]}.png",
                mime="image/png",
            )

    st.divider()
    st.subheader("Реестр соответствий «оригинал ↔ наш код»")
    st.caption("Не привязан к конкретному чертежу выше — общий журнал по всем закупкам.")

    if "code_registry" not in st.session_state:
        st.session_state["code_registry"] = []

    rc1, rc2 = st.columns(2)
    original_value = rc1.text_input("Оригинальный номер/код детали или заказчик", value="", key="draw_original_input")
    note_value = rc2.text_input("Примечание (необязательно)", value="", key="draw_note_input")

    if st.button("Сгенерировать код и добавить в реестр →"):
        if not original_value.strip():
            st.error("Заполните оригинальный номер/код или заказчика.")
        else:
            existing_codes = [m.internal_code for m in st.session_state["code_registry"]]
            new_code = generate_internal_code(existing_codes)
            st.session_state["code_registry"].append(CodeMapping(original_value.strip(), new_code, note_value.strip()))
            st.success(f"Добавлено: {original_value.strip()} → {new_code}")

    registry = st.session_state["code_registry"]
    if registry:
        st.dataframe(
            [{"Оригинал": m.original, "Наш код": m.internal_code, "Примечание": m.note} for m in registry],
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "📥 Скачать реестр (.csv)",
            data=registry_to_csv(registry),
            file_name="реестр_соответствий.csv",
            mime="text/csv",
        )
    else:
        st.caption("Реестр пока пуст — добавьте первую запись выше.")
