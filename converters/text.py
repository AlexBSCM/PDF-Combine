"""Raw-конвертация txt/md в PDF (простой текстовый рендер, поддержка кириллицы)."""
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_UNICODE_FONT_NAME = "AppUnicodeFont"
_font_registered = False

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
)


def _ensure_unicode_font() -> str:
    global _font_registered
    if _font_registered:
        return _UNICODE_FONT_NAME
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(_UNICODE_FONT_NAME, path))
                _font_registered = True
                return _UNICODE_FONT_NAME
            except Exception:
                continue
    return "Helvetica"


def _read_text(input_path: str) -> str:
    with open(input_path, "rb") as f:
        data = f.read()
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def text_to_pdf(input_path: str, output_path: str, font_size: int = 11) -> None:
    text = _read_text(input_path)
    font_name = _ensure_unicode_font()

    c = canvas.Canvas(output_path, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    line_height = font_size * 1.4
    max_width = width - 2 * margin

    c.setFont(font_name, font_size)
    y = height - margin

    for raw_line in text.splitlines() or [""]:
        for line in _wrap_line(c, raw_line, font_name, font_size, max_width):
            if y < margin:
                c.showPage()
                c.setFont(font_name, font_size)
                y = height - margin
            c.drawString(margin, y, line)
            y -= line_height

    c.save()


def _wrap_line(c: canvas.Canvas, line: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    if not line:
        return [""]
    wrapped, current = [], ""
    for word in line.split(" "):
        candidate = f"{current} {word}".strip() if current else word
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        if current:
            wrapped.append(current)
        current = _split_long_word(c, word, font_name, font_size, max_width, wrapped)
    if current:
        wrapped.append(current)
    return wrapped or [""]


def _split_long_word(
    c: canvas.Canvas,
    word: str,
    font_name: str,
    font_size: int,
    max_width: float,
    wrapped: list[str],
) -> str:
    """Разрезает слово шире max_width по строкам; возвращает остаток."""
    while c.stringWidth(word, font_name, font_size) > max_width:
        lo, hi, best = 1, len(word), 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if c.stringWidth(word[:mid], font_name, font_size) <= max_width:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        wrapped.append(word[:best])
        word = word[best:]
    return word
