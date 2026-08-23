"""
Локальное сохранение настроек (ключи ИИ, вебхук Bitrix24)
==============================================================

Streamlit держит всё, что вы вводите в интерфейсе, только в памяти
текущего сеанса — при перезапуске сервера (например, когда обновляется
код приложения) всё стирается, и ключи/вебхук приходится вбивать заново.
Раздражает при активной разработке, поэтому сохраняем на диск.

Файл настроек (SETTINGS_FILE) содержит секреты в открытом виде — это
нормально для личного использования на своём компьютере, но НЕЛЬЗЯ
заливать его на GitHub или куда-либо ещё. Он уже добавлен в .gitignore.

Сохранение на диск включается ТОЛЬКО если рядом лежит маркер-файл
LOCAL_DEV_MARKER — он тоже в .gitignore и никогда не попадёт в публичный
деплой (Streamlit Community Cloud). Без маркера load/save_settings — это
no-op: настройки живут только в session_state текущей вкладки браузера
и не сохраняются на сервере. Так публичное демо не может "утечь" секрет
одного посетителя в сессию следующего.
"""

import json
from pathlib import Path

# файл настроек лежит в корне проекта (рядом с app.py), а не рядом с этим
# файлом — модуль живёт в modules/settings/, но хранить секреты хочется
# в одном стабильном месте независимо от того, куда переедет сам модуль
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = PROJECT_ROOT / ".local_settings.json"
LOCAL_DEV_MARKER = PROJECT_ROOT / ".local_dev_marker"

# какие ключи session_state сохраняем — только настройки интеграций,
# не рабочие данные конкретного тендера (те и не должны переживать сеанс)
PERSISTED_KEYS = [
    "llm_source",
    "yandex_api_key",
    "yandex_folder_id",
    "gigachat_credentials",
    "gigachat_skip_ssl",
    "bitrix_webhook_url",
    "bitrix_responsible_id",
    "bitrix_ceo_id",
]


def load_settings(path: Path = SETTINGS_FILE) -> dict:
    if not LOCAL_DEV_MARKER.exists() or not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(values: dict, path: Path = SETTINGS_FILE) -> None:
    if not LOCAL_DEV_MARKER.exists():
        return
    data = {k: v for k, v in values.items() if k in PERSISTED_KEYS}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # самотест пишет во ВРЕМЕННЫЙ файл, а не в настоящий SETTINGS_FILE — тот
    # уже может содержать настоящие сохранённые ключи пользователя, тест не
    # должен их затирать или удалять
    test_path = PROJECT_ROOT / ".local_settings.selftest.json"
    demo = {
        "llm_source": "GigaChat",
        "gigachat_credentials": "test-key-12345",
        "bitrix_webhook_url": "https://example.bitrix24.ru/rest/1/xxxx/",
        "bitrix_responsible_id": 7,
        "bitrix_ceo_id": 1,
        "should_not_be_saved": "мусор, не из PERSISTED_KEYS",
    }

    # реальный маркер (если есть, например уже стоит на этом компьютере)
    # на время теста откладываем в сторону и потом возвращаем как было
    real_marker_existed = LOCAL_DEV_MARKER.exists()
    if real_marker_existed:
        LOCAL_DEV_MARKER.rename(LOCAL_DEV_MARKER.with_suffix(".bak"))

    try:
        without_marker_path = PROJECT_ROOT / ".local_settings.selftest2.json"
        save_settings(demo, path=without_marker_path)
        assert not without_marker_path.exists(), "без маркера save_settings обязан быть no-op"
        assert load_settings(path=without_marker_path) == {}, "без маркера load_settings обязан вернуть {}"
        print("Без .local_dev_marker сохранение/загрузка отключены — как в публичном демо. Проверено.")

        LOCAL_DEV_MARKER.touch()
        save_settings(demo, path=test_path)
        loaded = load_settings(path=test_path)
        print("С маркером — сохранено и прочитано обратно (во временный тестовый файл):")
        print(loaded)
        assert loaded["gigachat_credentials"] == "test-key-12345"
        assert loaded["bitrix_webhook_url"] == demo["bitrix_webhook_url"]
        assert "should_not_be_saved" not in loaded, "лишние ключи не должны сохраняться"
        print("\nПроверка пройдена.")
        test_path.unlink()
    finally:
        LOCAL_DEV_MARKER.unlink(missing_ok=True)
        if real_marker_existed:
            LOCAL_DEV_MARKER.with_suffix(".bak").rename(LOCAL_DEV_MARKER)
    print("Временный тестовый файл удалён — настоящий файл настроек (если есть) не тронут.")
