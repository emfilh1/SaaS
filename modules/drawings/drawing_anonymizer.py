"""
Обезличивание чертежей + реестр соответствий
=================================================

Рабочий процесс, который раньше делали вручную: взяли чертёж (в том
числе скан) → закрасили на нём заказчика/номера/коды → присвоили свой
внутренний код → записали в таблицу «оригинал ↔ наш код», чтобы потом
можно было найти исходник по своему коду и наоборот.

Три независимых куска:
1. Закраска чувствительных зон на изображении (Pillow, работает
   офлайн, без интернета и ИИ) — координаты прямоугольников передаются
   снаружи (в интерфейсе их рисуют мышкой поверх картинки).
2. Реестр соответствий «оригинал -> наш код» — простой список пар с
   выгрузкой в CSV (открывается в Excel).
3. Необязательные OCR-подсказки (suggest_text_regions_ocr) — находят,
   где на чертеже вообще есть текст, чтобы не искать глазами по всему
   листу. Это ТОЛЬКО подсказка, не автоматическая закраска: OCR может
   промахнуться мимо рукописного текста, нестандартного штампа или,
   наоборот, отметить размер/допуск, который на самом деле закрашивать
   не нужно — рисование прямоугольников руками (пункт 1) остаётся
   основным способом и никуда не делось.

Ограничение сейчас: принимает изображения (PNG/JPG/BMP/TIFF — то, что
приходит как скан). PDF-чертежи нужно сначала превратить в изображение
(например, скриншотом страницы) — прямая работа с PDF потребует
дополнительную системную зависимость (poppler), которую не с чем было
проверить в этой среде.
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageDraw


@dataclass
class CodeMapping:
    original: str        # оригинальный номер/код детали или наименование заказчика
    internal_code: str    # наш внутренний придуманный код
    note: str = ""


def generate_internal_code(existing_codes: list[str], prefix: str = "КП") -> str:
    """Следующий свободный код вида КП-0001, КП-0002... — не полагаемся на
    len(existing_codes)+1, чтобы не столкнуться с уже занятым номером после
    ручного удаления записи из реестра."""
    used_numbers = set()
    for code in existing_codes:
        if code.startswith(f"{prefix}-"):
            suffix = code[len(prefix) + 1:]
            if suffix.isdigit():
                used_numbers.add(int(suffix))
    next_number = 1
    while next_number in used_numbers:
        next_number += 1
    return f"{prefix}-{next_number:04d}"


def redact_image(image: Image.Image, rectangles: list[tuple[int, int, int, int]], fill=(0, 0, 0)) -> Image.Image:
    """Закрашивает прямоугольники (x1, y1, x2, y2) в пикселях исходного
    изображения. Не изменяет переданный image — работает с копией."""
    redacted = image.convert("RGB").copy()
    draw = ImageDraw.Draw(redacted)
    for x1, y1, x2, y2 in rectangles:
        draw.rectangle([x1, y1, x2, y2], fill=fill)
    return redacted


# ------------------------------------------------------- OCR-подсказки (опц.)

@dataclass
class OcrSuggestion:
    box: tuple[int, int, int, int]
    text: str
    confidence: float


def suggest_text_regions_ocr(image: Image.Image, languages: Optional[list[str]] = None) -> list[OcrSuggestion]:
    """Находит текстовые области на изображении — только подсказка, куда
    смотреть, не автоматическая закраска (см. предупреждение в докстринге
    модуля выше).

    Требует необязательную тяжёлую зависимость easyocr (тянет PyTorch;
    при первом вызове на новой машине скачивает модели распознавания,
    занимает время и требует интернет один раз). Если пакет не
    установлен — кидает понятный ImportError с инструкцией вместо
    невнятного падения."""
    try:
        import numpy as np
        import easyocr
    except ImportError as e:
        raise ImportError(
            "Для OCR-подсказок нужен пакет easyocr (тяжёлая необязательная "
            "зависимость): pip install easyocr"
        ) from e

    reader = easyocr.Reader(languages or ["ru", "en"], gpu=False)
    results = reader.readtext(np.array(image.convert("RGB")))

    suggestions = []
    for bbox, text, confidence in results:
        xs = [point[0] for point in bbox]
        ys = [point[1] for point in bbox]
        box = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
        suggestions.append(OcrSuggestion(box=box, text=text, confidence=float(confidence)))
    return suggestions


def draw_suggestion_overlay(image: Image.Image, suggestions: list[OcrSuggestion], outline=(255, 0, 0)) -> Image.Image:
    """Рисует контуры (не закрашивает!) вокруг найденных OCR областей —
    справочная картинка, по которой человек ориентируется, что и где
    закрашивать на настоящем холсте. Не изменяет исходное изображение."""
    preview = image.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)
    for s in suggestions:
        draw.rectangle(list(s.box), outline=outline, width=3)
    return preview


def registry_to_csv(mappings: list[CodeMapping]) -> bytes:
    """CSV с BOM — чтобы кириллица корректно открывалась в Excel без
    ручного указания кодировки при импорте."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Оригинал (заказчик/номер)", "Наш внутренний код", "Примечание"])
    for m in mappings:
        writer.writerow([m.original, m.internal_code, m.note])
    return buf.getvalue().encode("utf-8-sig")


if __name__ == "__main__":
    # 1. Генерация кодов без коллизий
    codes = []
    for _ in range(3):
        new_code = generate_internal_code(codes)
        codes.append(new_code)
    print("Сгенерированные коды:", codes)
    assert codes == ["КП-0001", "КП-0002", "КП-0003"]

    # код после "ручного удаления" среднего — новый код не должен повторяться
    codes_with_gap = ["КП-0001", "КП-0003"]
    next_code = generate_internal_code(codes_with_gap)
    print("Следующий код при пропуске КП-0002:", next_code)
    assert next_code == "КП-0002"

    # 2. Закраска изображения
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    redacted = redact_image(img, [(10, 10, 90, 40)])
    assert redacted.getpixel((50, 25)) == (0, 0, 0), "область должна быть закрашена чёрным"
    assert redacted.getpixel((150, 80)) == (255, 255, 255), "остальное изображение не должно измениться"
    assert img.getpixel((50, 25)) == (255, 255, 255), "исходное изображение не должно мутироваться"
    print("Закраска изображения: пиксели проверены, оригинал не изменён.")

    # 3. Реестр в CSV
    mappings = [
        CodeMapping("АО «Заказчик-1», деталь 12345-67", "КП-0001", "чертёж от 2026-08-01"),
        CodeMapping("ООО «Заказчик-2», узел А-9", "КП-0002"),
    ]
    csv_bytes = registry_to_csv(mappings)
    csv_text = csv_bytes.decode("utf-8-sig")
    assert "КП-0001" in csv_text and "Заказчик-1" in csv_text
    print("\nCSV реестра:\n" + csv_text)

    # 4. OCR-подсказки (необязательная зависимость — пропускаем, если не установлена)
    try:
        from PIL import ImageDraw as _ImageDraw
        text_img = Image.new("RGB", (400, 100), color=(255, 255, 255))
        _ImageDraw.Draw(text_img).text((20, 30), "ЗАКАЗЧИК ООО ТЕСТ", fill=(0, 0, 0))
        suggestions = suggest_text_regions_ocr(text_img)
        print(f"\nOCR нашёл областей с текстом: {len(suggestions)}")
        for s in suggestions:
            print(f"  область {s.box}, распознано {s.text!r} (уверенность {s.confidence:.2f})")
        assert len(suggestions) >= 1, "должна найтись хотя бы одна текстовая область"
        overlay = draw_suggestion_overlay(text_img, suggestions)
        assert overlay.size == text_img.size
        print("OCR-подсказки: область найдена, справочная картинка построена.")
    except ImportError as e:
        print(f"\nOCR-подсказки пропущены (необязательная зависимость не установлена): {e}")

    print("\nПроверка пройдена: все функции модуля работают корректно.")
