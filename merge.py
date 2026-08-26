"""Объединение и разделение PDF."""
from pypdf import PdfReader, PdfWriter


def merge_pdfs(pdf_paths: list[str], output_path: str) -> None:
    writer = PdfWriter()
    for path in pdf_paths:
        writer.append(path)
    with open(output_path, "wb") as f:
        writer.write(f)


def parse_pages(spec: str, total: int | None = None) -> list[int]:
    """'1-3,5' -> [1, 2, 3, 5]. Дубликаты убираются с сохранением порядка."""
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            if not lo_s.isdigit() or not hi_s.isdigit():
                raise ValueError(f"Неверный диапазон: {part}")
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi or lo < 1:
                raise ValueError(f"Неверный диапазон: {part}")
            pages.extend(range(lo, hi + 1))
        elif part.isdigit():
            if int(part) < 1:
                raise ValueError(f"Номер страницы должен быть >= 1: {part}")
            pages.append(int(part))
        else:
            raise ValueError(f"Неверный фрагмент: {part}")
    if not pages:
        raise ValueError("Не указано ни одной страницы")
    if total is not None and max(pages) > total:
        raise ValueError(f"Страницы {max(pages)} нет в документе (всего {total})")
    seen: set[int] = set()
    return [p for p in pages if not (p in seen or seen.add(p))]


def split_pdf(input_path: str, page_numbers: list[int], output_path: str) -> int:
    """Извлекает страницы (нумерация с 1) в новый PDF. Возвращает их количество."""
    reader = PdfReader(input_path)
    count = len(reader.pages)
    writer = PdfWriter()
    for n in page_numbers:
        if not 1 <= n <= count:
            raise ValueError(f"Страницы {n} нет в документе (всего {count})")
        writer.add_page(reader.pages[n - 1])
    with open(output_path, "wb") as f:
        writer.write(f)
    return len(page_numbers)
