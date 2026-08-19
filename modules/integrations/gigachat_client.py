"""
Клиент к GigaChat (Сбер) — через официальный SDK ai-forever/gigachat
========================================================================

Та же логика, что в yandexgpt_client.py: функция call_gigachat(prompt) ->
строка с ответом модели, готовая к передаче в
requirement_extractor.parse_llm_response().

Что нужно, чтобы заработало (пока не проверялось "вживую" — нет ключа):
1. pip install gigachat  (проверено — ставится без проблем)
2. Получить Authorization key в личном кабинете GigaChat API (developers.sber.ru).
3. Передать сюда CREDENTIALS.

Технический нюанс, который часто ломает первый запуск: GigaChat требует
доверенный российский корневой сертификат (Минцифры) для TLS. Официальный
SDK умеет либо использовать verify_ssl_certs=False (быстро, но небезопасно
для продакшена), либо принять путь к сертификату — см. документацию SDK.

Источники (август 2026):
- https://github.com/ai-forever/gigachat
- https://pypi.org/project/gigachat/

Ловушка, найденная при реальном запуске внутри Streamlit: SDK gigachat
внутри синхронно оборачивает httpx поверх asyncio и ждёт event loop в
текущем потоке. В обычном скрипте это всегда главный поток — там loop
либо уже есть, либо Python создаёт его сам. Streamlit выполняет код
приложения в отдельном потоке (ScriptRunner.scriptThread), где event
loop по умолчанию не создан — оттуда и ошибка "There is no current
event loop in thread 'ScriptRunner.scriptThread'". Чиним явным
созданием event loop для текущего потока перед вызовом SDK — безопасно
вызывать многократно, если loop уже есть, ничего не переопределяем.
"""

import asyncio

from gigachat import GigaChat


def _ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def call_gigachat(
    prompt: str,
    credentials: str,
    scope: str = "GIGACHAT_API_PERS",  # PERS — физлицо, B2B/CORP — для юрлиц, уточнить при подключении
    model: str = "GigaChat-2-Pro",     # для сложной документации; для рутинной фильтрации хватит "GigaChat" (базовая)
    temperature: float = 0.1,
    verify_ssl_certs: bool = True,      # False — только для быстрой локальной проверки, не для продакшена
) -> str:
    _ensure_event_loop()
    with GigaChat(
        credentials=credentials,
        scope=scope,
        model=model,
        verify_ssl_certs=verify_ssl_certs,
    ) as giga:
        response = giga.chat({
            "messages": [
                {"role": "system", "content": "Отвечай только валидным JSON, без пояснений и markdown-разметки."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        })
        return response.choices[0].message.content


if __name__ == "__main__":
    import os

    credentials = os.environ.get("GIGACHAT_CREDENTIALS")
    if not credentials:
        print("Задай переменную окружения GIGACHAT_CREDENTIALS (Authorization key), чтобы проверить клиент вживую.")
        raise SystemExit(0)

    reply = call_gigachat('Ответь строкой JSON: {"ok": true}', credentials)
    print("Ответ модели:", reply)
