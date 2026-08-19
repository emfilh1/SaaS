"""
Клиент к сервису отдачи информации ЕИС (zakupki.gov.ru)
=========================================================

Что это: скачивает архив с извещениями о закупках (тендерами) за нужный
регион/период через официальный SOAP-сервис ЕИС. Это первый кирпичик
модуля "Радар тендеров" — дальше эти файлы можно фильтровать по ключевым
словам/ОКПД2 и скармливать в AI (YandexGPT/GigaChat) для разбора.

Как запустить:
1. Получить токен: https://zakupki.gov.ru/pmd/auth/welcome -> Госуслуги ->
   "Регистрация нового потребителя машиночитаемых данных" -> физлицо/ИП.
2. pip install requests xmltodict
3. Заполнить блок НАСТРОЙКИ ниже (токен, регион, дата, тип документа).
4. python3 eis_client.py

Важно про регион (orgRegion): это код региона заказчика по классификатору
ЕИС (не всегда совпадает с обычным кодом региона РФ) — точный код лучше
свериться в справочнике НСИ ЕИС (метод getNsiRequest) или посмотреть в
руководстве "Инструкция по использованию сервисов отдачи информации ЕИС"
на zakupki.gov.ru — я не гарантирую совпадение с общероссийским ОКАТО/ОКТМО.

Важно про documentType44: пример ниже — "epNotificationEF2020" (извещение
об электронном аукционе). Полный список типов документов и обязательных
параметров для каждого метода — в интеграционной схеме:
https://int44.zakupki.gov.ru/eis-integration/services/getDocsIP?xsd=getDocsIP-ws-api.xsd
Это нужно свериться отдельно перед боевым использованием.

Источник структуры запроса и рабочего примера кода:
https://habr.com/ru/articles/869934/
"""

import uuid
import datetime
import zipfile
import io
import requests
import xmltodict

# ---------------- НАСТРОЙКИ (заполнить перед запуском) ----------------

TOKEN = "ВСТАВЬ_СЮДА_СВОЙ_ТОКЕН"     # из личного кабинета zakupki.gov.ru/pmd
ORG_REGION = "72"                     # код региона заказчика (пример из статьи — Тюменская обл.), проверить свой
DOCUMENT_TYPE_44 = "epNotificationEF2020"  # тип документа (пример: извещение об электронном аукционе)
EXACT_DATE = datetime.date.today().strftime("%Y-%m-%d")  # дата, за которую тянем извещения (YYYY-MM-DD)

URL = "https://int44.zakupki.gov.ru/eis-integration/services/getDocsIP"

# ---------------- Сборка SOAP-запроса ----------------

def build_request_xml(token: str, org_region: str, document_type: str, exact_date: str) -> str:
    request_id = str(uuid.uuid4())
    created_at = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ws="http://zakupki.gov.ru/fz44/get-docs-ip/ws">
   <soapenv:Header>
      <individualPerson_token>{token}</individualPerson_token>
   </soapenv:Header>
   <soapenv:Body>
      <ws:getDocsByOrgRegionRequest>
         <index>
            <id>{request_id}</id>
            <createDateTime>{created_at}</createDateTime>
            <mode>PROD</mode>
         </index>
         <selectionParams>
            <orgRegion>{org_region}</orgRegion>
            <subsystemType>PRIZ</subsystemType>
            <documentType44>{document_type}</documentType44>
            <periodInfo>
               <exactDate>{exact_date}</exactDate>
            </periodInfo>
         </selectionParams>
      </ws:getDocsByOrgRegionRequest>
   </soapenv:Body>
</soapenv:Envelope>"""


def _find_by_local_name(node: dict, local_name: str) -> dict:
    """Достаёт узел по имени без учёта namespace-префикса (soap:/soapenv:/... —
    реальный префикс сервера ЕИС не проверялся вживую, поэтому не завязываемся
    на конкретный, ищем любой ключ, который заканчивается на нужное имя)."""
    key = next((k for k in node if k == local_name or k.endswith(f":{local_name}")), None)
    if key is None:
        raise RuntimeError(f"Не нашёл узел '{local_name}' в ответе ЕИС. Получено: {list(node)}")
    return node[key]


def request_archive_url(token: str, org_region: str, document_type: str, exact_date: str) -> str:
    xml_data = build_request_xml(token, org_region, document_type, exact_date)
    headers = {"Content-Type": "text/xml; charset=utf-8"}
    response = requests.post(URL, data=xml_data.encode("utf-8"), headers=headers, timeout=30)
    response.raise_for_status()
    parsed = xmltodict.parse(response.content)
    envelope = _find_by_local_name(parsed, "Envelope")
    body = _find_by_local_name(envelope, "Body")
    # имя ключа ответа зависит от метода — ищем по подстроке на случай, если сервис вернул ошибку
    response_key = next((k for k in body if "getDocsByOrgRegionResponse" in k), None)
    if response_key is None:
        raise RuntimeError(f"Неожиданный ответ сервиса ЕИС: {body}")
    data_info = body[response_key].get("dataInfo")
    if not data_info or "archiveUrl" not in data_info:
        raise RuntimeError(f"Сервис не вернул ссылку на архив. Полный ответ: {body[response_key]}")
    return data_info["archiveUrl"]


def download_archive(archive_url: str, token: str) -> bytes:
    headers = {"individualPerson_token": token}
    response = requests.get(archive_url, headers=headers, timeout=120)
    response.raise_for_status()
    return response.content


def list_archive_contents(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = zf.namelist()
        print(f"В архиве {len(names)} файлов:")
        for name in names[:20]:
            print(" -", name)
        if len(names) > 20:
            print(f"   ...и ещё {len(names) - 20}")
        return names


if __name__ == "__main__":
    if TOKEN == "ВСТАВЬ_СЮДА_СВОЙ_ТОКЕН":
        print("Сначала заполни TOKEN в блоке НАСТРОЙКИ (получить на zakupki.gov.ru/pmd/auth/welcome).")
        raise SystemExit(1)

    print(f"Запрашиваю извещения: регион={ORG_REGION}, дата={EXACT_DATE}, тип={DOCUMENT_TYPE_44}")
    archive_url = request_archive_url(TOKEN, ORG_REGION, DOCUMENT_TYPE_44, EXACT_DATE)
    print("Ссылка на архив получена, скачиваю...")
    archive_bytes = download_archive(archive_url, TOKEN)
    print(f"Скачано {len(archive_bytes) / 1024:.1f} КБ")
    list_archive_contents(archive_bytes)
