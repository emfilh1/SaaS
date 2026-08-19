"""
Клиент к YandexGPT (Yandex Foundation Models API)
====================================================

Подставляется вместо requirement_extractor._mock_llm в pipeline.py —
сигнатура та же: функция принимает prompt (строку) и возвращает ответ
модели (строку). Поскольку наш промпт в requirement_extractor.py явно
просит модель вернуть только JSON, ответ можно сразу передавать в
parse_llm_response().

Что нужно, чтобы заработало (пока не проверялось "вживую" — нет ключа):
1. Завести сервисный аккаунт / API-ключ в Yandex Cloud, каталог (folder).
2. pip install requests (уже используется в eis_client.py).
3. Передать сюда API_KEY и FOLDER_ID.

Источники (структура запроса подтверждена веб-поиском, август 2026):
- https://yandex.cloud/en/docs/foundation-models/quickstart/yandexgpt
- https://github.com/roma1n/yandexgpt-api-python-example
"""

import json
import requests

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def call_yandexgpt(
    prompt: str,
    api_key: str,
    folder_id: str,
    model: str = "yandexgpt-lite/latest",  # для сложной документации разумнее "yandexgpt/latest" или "yandexgpt-5-pro/latest"
    temperature: float = 0.1,               # низкая температура — для извлечения фактов, не для творчества
    max_tokens: int = 2000,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id": folder_id,
    }
    body = {
        "modelUri": f"gpt://{folder_id}/{model}",
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": str(max_tokens),
        },
        "messages": [
            {"role": "system", "text": "Отвечай только валидным JSON, без пояснений и markdown-разметки."},
            {"role": "user", "text": prompt},
        ],
    }
    response = requests.post(COMPLETION_URL, headers=headers, data=json.dumps(body), timeout=60)
    response.raise_for_status()
    data = response.json()
    # структура ответа: result.alternatives[0].message.text
    return data["result"]["alternatives"][0]["message"]["text"]


if __name__ == "__main__":
    import os

    api_key = os.environ.get("YANDEX_API_KEY")
    folder_id = os.environ.get("YANDEX_FOLDER_ID")
    if not api_key or not folder_id:
        print("Задай переменные окружения YANDEX_API_KEY и YANDEX_FOLDER_ID, чтобы проверить клиент вживую.")
        raise SystemExit(0)

    reply = call_yandexgpt("Ответь строкой JSON: {\"ok\": true}", api_key, folder_id)
    print("Ответ модели:", reply)
