# Тендер-помощник — AI-ассистент для участия в тендерах (сторона поставщика)

Прототип продукта из стратегии (см. `PROJECT_BRIEF.md`). Веб-интерфейс на Streamlit
поверх набора независимых Python-модулей — каждый модуль можно запустить и
проверить отдельно от интерфейса (см. «Как проверить модули по отдельности» ниже).

## Быстрый старт

```bash
pip install -r requirements.txt
streamlit run app.py
```

Откроется `http://localhost:8501`. По умолчанию работает в демо-режиме (без
ключей ИИ и токена ЕИС) — все вкладки кликабельны на тестовых данных.

## Структура проекта

```
app.py                     — точка входа, весь интерфейс Streamlit (9 вкладок)
requirements.txt           — обязательные зависимости
requirements-optional.txt  — тяжёлые необязательные (сейчас: easyocr для чертежей)
.streamlit/config.toml     — тема оформления, настройки Streamlit
.local_settings.json       — сохранённые ключи/вебхуки (создаётся сам, в .gitignore)

modules/
├── core/            — общие модели данных + базовый конвейер разбора документации
│   ├── tender_models.py         (TenderRequirements, CompanyProfile, TenderNotice)
│   ├── requirement_extractor.py (промпт для ИИ + разбор JSON-ответа)
│   └── analysis_pipeline.py     (склейка: текст → требования → чек-лист рисков)
├── radar/           — модуль 1: Радар тендеров (фильтры, плюс/минус-слова, ИИ-поиск)
│   └── tender_radar.py
├── workflow/        — карточка тендера с этапами (Конвейер)
│   └── tender_pipeline.py
├── compliance/       — модуль 3: линтер заявки (чек-лист по 44-ФЗ)
│   └── tender_application_linter.py
├── pricing/         — модуль 4: антидемпинг (ст. 37 44-ФЗ) + предварительная цена
│   ├── price_risk_calculator.py
│   └── preliminary_pricing.py
├── documents/       — генератор бланков + извлечение текста из PDF/DOCX
│   ├── document_generator.py
│   └── document_text_extractor.py
├── tracking/        — модуль 5: дедлайны после победы + экспорт в .ics
│   ├── post_contract_tracker.py
│   └── ics_export.py
├── drawings/        — обезличивание чертежей (вручную + автоматически через OCR)
│   └── drawing_anonymizer.py
├── integrations/    — клиенты внешних систем
│   ├── eis_client.py         (ЕИС, SOAP — готов, не подключён к интерфейсу)
│   ├── yandexgpt_client.py   (YandexGPT)
│   ├── gigachat_client.py    (GigaChat)
│   ├── bitrix24_client.py    (задачи/календарь/дайджест ГД)
│   └── seldon_client.py      (заготовка — нет публичной техдокументации API)
└── settings/
    └── local_settings.py     (сохранение ключей между запусками)
```

Каждый файл внутри `modules/` — самостоятельный, у каждого есть `if __name__ ==
"__main__":` с самотестом на демо-данных, без зависимости от Streamlit.

## Статус модулей продукта

| Модуль | Статус | Комментарий |
|---|---|---|
| 1. Радар тендеров | 🟡 работает на демо-потоке | нужен токен ЕИС для реальных извещений |
| 2. Экстрактор требований | ✅ работает | демо-режим (мок) или реальный YandexGPT/GigaChat |
| 3. Линтер заявки | ✅ работает | |
| 4. Калькулятор цены и рисков | ✅ работает | |
| 5. Пост-контрактный трекер | ✅ работает | |
| Генератор документов (бонус) | ✅ работает | не входил в исходную стратегию |
| Обезличивание чертежей (бонус) | ✅ работает | ручная закраска + автоматическая через OCR |

## Как проверить модули по отдельности (без Streamlit)

Запускать из корня проекта флагом `-m` (не напрямую путём к файлу — модули
ссылаются друг на друга через пакет `modules`):

```bash
python3 -m modules.compliance.tender_application_linter
python3 -m modules.core.analysis_pipeline
python3 -m modules.pricing.price_risk_calculator
python3 -m modules.pricing.preliminary_pricing
python3 -m modules.tracking.post_contract_tracker
python3 -m modules.tracking.ics_export
python3 -m modules.radar.tender_radar
python3 -m modules.workflow.tender_pipeline
python3 -m modules.drawings.drawing_anonymizer
python3 -m modules.documents.document_generator
python3 -m modules.documents.document_text_extractor
python3 -m modules.integrations.bitrix24_client
python3 -m modules.settings.local_settings
```

## Подключение реальных сервисов

**Токен ЕИС** (`modules/integrations/eis_client.py`) — бесплатно, 5 минут:
`zakupki.gov.ru/pmd/auth/welcome` → Госуслуги → «Регистрация нового потребителя
машиночитаемых данных». Написан по документации, не проверялся вживую.

**YandexGPT / GigaChat** — ключи вводятся прямо в интерфейсе (сайдбар слева,
«Источник ИИ»), сохраняются в `.local_settings.json` между запусками. GigaChat
требует сертификат Минцифры для TLS — если ловите `CERTIFICATE_VERIFY_FAILED`,
временный обход есть в виде чекбокса рядом с полем ключа.

**Bitrix24** — входящий вебхук: Приложения → Разработчикам → Другое → Входящий
вебхук, права минимум «Задачи» и «Календарь». Вставить в сайдбар.

**Seldon** — заготовка интерфейса без реализации: публичная документация API не
раскрывает технические детали (адрес, авторизация). Нужно запросить у Seldon
напрямую как у подключённого клиента. См. докстринг `seldon_client.py`.

## Дальше по плану

Из стратегии (`PROJECT_BRIEF.md`, план на первый месяц): технический аудит ЕИС и
площадок компании → прогон реальных документов через экстрактор → донастройка и
условия пилота → решение по MVP.
