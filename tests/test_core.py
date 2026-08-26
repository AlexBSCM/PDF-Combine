"""Тесты ядра конвертеров (без GUI). Office-тесты включаются переменной
окружения PDFCONV_TEST_OFFICE=1 на машине с установленным MS Office."""
import os

import pytest
from pypdf import PdfReader
from PIL import Image

from converters.htmlpdf import find_browser, html_to_pdf
from converters.images import images_to_pdf
from converters.preview import render_compressed
from converters.text import text_to_pdf
from gs_locator import find_ghostscript
from merge import merge_pdfs, parse_pages, split_pdf
from optimize import QualitySettings, _qfactor, optimize_pdf
import app as appmod


@pytest.fixture()
def tmp_out(tmp_path):
    return tmp_path


def test_text_cyrillic_cp1251(tmp_out):
    src = tmp_out / "t.txt"
    src.write_bytes("Привет, мир! ЩЪЁ\n".encode("cp1251"))
    dst = tmp_out / "t.pdf"
    text_to_pdf(str(src), str(dst))
    assert "Привет" in PdfReader(str(dst)).pages[0].extract_text()


def test_text_utf8_and_multipage(tmp_out):
    src = tmp_out / "t.md"
    src.write_text("Строка один\n" * 400, encoding="utf-8")
    dst = tmp_out / "t.pdf"
    text_to_pdf(str(src), str(dst))
    assert len(PdfReader(str(dst)).pages) > 1


def test_text_long_word_no_crash(tmp_out):
    src = tmp_out / "long.txt"
    src.write_text("X" * 3000 + "\n", encoding="utf-8")
    dst = tmp_out / "long.pdf"
    text_to_pdf(str(src), str(dst))
    assert len(PdfReader(str(dst)).pages) >= 1


def test_images_alpha_flattened(tmp_out):
    alpha = tmp_out / "a.png"
    Image.new("RGBA", (120, 80), (255, 0, 0, 128)).save(alpha)
    jpg = tmp_out / "b.jpg"
    Image.new("RGB", (60, 60), (0, 255, 0)).save(jpg)
    dst = tmp_out / "imgs.pdf"
    images_to_pdf([str(alpha), str(jpg)], str(dst))
    assert len(PdfReader(str(dst)).pages) == 2


def test_merge_order(tmp_out):
    pdfs = []
    for i in range(3):
        src = tmp_out / f"m{i}.txt"
        src.write_text(f"MARK{i}\n", encoding="utf-8")
        pdf = tmp_out / f"m{i}.pdf"
        text_to_pdf(str(src), str(pdf))
        pdfs.append(str(pdf))
    dst = tmp_out / "merged.pdf"
    merge_pdfs(pdfs, str(dst))
    pages = [p.extract_text() or "" for p in PdfReader(str(dst)).pages]
    assert len(pages) == 3
    assert all(f"MARK{i}" in pages[i] for i in range(3))


def test_parse_pages():
    assert parse_pages("1-3,5") == [1, 2, 3, 5]
    assert parse_pages("7") == [7]
    assert parse_pages("1,1,2") == [1, 2]
    with pytest.raises(ValueError):
        parse_pages("abc")
    with pytest.raises(ValueError):
        parse_pages("")
    with pytest.raises(ValueError):
        parse_pages("3-1")
    with pytest.raises(ValueError):
        parse_pages("1-10", total=5)


def test_split_pdf(tmp_out):
    src = tmp_out / "s.txt"
    src.write_text("\n".join(f"P{i}" for i in range(400)), encoding="utf-8")
    full = tmp_out / "s.pdf"
    text_to_pdf(str(src), str(full))
    total = len(PdfReader(str(full)).pages)
    assert total >= 3
    dst = tmp_out / "part.pdf"
    count = split_pdf(str(full), parse_pages("1-2," + str(total)), str(dst))
    assert count == 3
    assert len(PdfReader(str(dst)).pages) == 3
    with pytest.raises(ValueError):
        split_pdf(str(full), [total + 1], str(dst))


def test_build_jobs_order_and_grouping():
    files = ["a.txt", "i1.png", "i2.jpg", "b.docx", "i3.webp"]
    jobs = appmod.build_jobs(files)
    kinds = [j[0] for j in jobs]
    assert kinds == ["file", "images", "file"]
    assert jobs[1][1] == ["i1.png", "i2.jpg", "i3.webp"]


def test_unique_pdf_path(tmp_path):
    stem = "doc"
    first = appmod.unique_pdf_path(str(tmp_path), stem)
    open(first, "wb").close()
    second = appmod.unique_pdf_path(str(tmp_path), stem)
    assert first != second and second.endswith("_2.pdf")


def test_gs_locator_type():
    result = find_ghostscript()
    assert result is None or (isinstance(result, str) and os.path.exists(result))


def test_html_to_pdf_if_browser(tmp_out):
    browser = find_browser()
    if not browser:
        pytest.skip("Edge/Chrome не найден")
    src = tmp_out / "page.html"
    src.write_text("<html><body><h1>HTMLTEST123</h1></body></html>", encoding="utf-8")
    dst = tmp_out / "page.pdf"
    html_to_pdf(str(src), str(dst), browser_path=browser)
    reader = PdfReader(str(dst))
    assert len(reader.pages) >= 1
    assert "HTMLTEST123" in (reader.pages[0].extract_text() or "")


@pytest.mark.skipif(
    os.environ.get("PDFCONV_TEST_OFFICE") != "1",
    reason="Требуется MS Office; включается PDFCONV_TEST_OFFICE=1",
)
def test_office_docx(tmp_path):
    import pythoncom
    from converters.office import OfficeSession

    word = None
    try:
        import win32com.client as win32
        pythoncom.CoInitialize()
        try:
            word = win32.Dispatch("Word.Application")
        except Exception:
            pytest.skip("MS Word не установлен")
        finally:
            pass
    finally:
        pass

    src = tmp_path / "o.docx"
    try:
        doc = word.Documents.Add()
        doc.Content.Text = "OFFICETEST"
        doc.SaveAs(os.path.abspath(src), FileFormat=16)
        doc.Close(False)
    finally:
        word.Quit()

    dst = tmp_path / "o.pdf"
    with OfficeSession() as office:
        office.convert(str(src), str(dst))
    assert "OFFICETEST" in (PdfReader(str(dst)).pages[0].extract_text() or "")

def test_pick_installer_asset():
    from gs_installer import pick_installer_asset

    assets = [
        {"name": "ghostpcl-10.07.1-win64.zip"},
        {"name": "gs10071w32.exe"},
        {"name": "gs10071w64.exe", "browser_download_url": "https://x/gs10071w64.exe"},
        {"name": "SHA512SUMS"},
    ]
    picked = pick_installer_asset(assets)
    assert picked and picked["name"] == "gs10071w64.exe"
    assert pick_installer_asset([{"name": "readme.txt"}]) is None


def test_fetch_latest_installer_url():
    from gs_installer import fetch_latest_installer_url

    info = fetch_latest_installer_url(timeout=30)
    assert info is not None
    url, tag = info
    assert url.startswith("https://") and url.endswith("w64.exe")
    assert tag.startswith("gs")


def test_install_ghostscript_noop_when_installed():
    from gs_installer import install_ghostscript

    result = install_ghostscript()
    if find_ghostscript():
        assert result and os.path.exists(result)
    else:
        assert result is None

def test_images_invalid_exif_rotation(tmp_out):
    im = Image.new("RGB", (150, 100), (10, 10, 200))
    ex = Image.Exif()
    ex[274] = 0
    src = tmp_out / "rot.jpg"
    im.save(src, quality=90, exif=ex.tobytes())
    dst = tmp_out / "rot.pdf"
    images_to_pdf([str(src)], str(dst))
    assert len(PdfReader(str(dst)).pages) == 1


def test_copy_log_button():
    from app import App

    app = App()
    app.withdraw()
    app.log.insert("1.0", "LINE1\nLINE2")
    app.copy_log()
    assert app.clipboard_get() == "LINE1\nLINE2"
    event = type("E", (), {})()
    assert app._log_ctrl_c(event) == "break"
    assert app.clipboard_get() == "LINE1\nLINE2"
    app.destroy()


def test_preview_render_smaller_at_low_quality(tmp_out):
    im = Image.new("RGB", (2000, 1500), (120, 30, 200))
    src = tmp_out / "big.jpg"
    im.save(src, quality=95)
    _, hi = render_compressed(str(src), 150, 95, False)
    _, lo = render_compressed(str(src), 40, 15, False)
    assert lo < hi
    comp_gray, _ = render_compressed(str(src), 150, 80, True)
    assert comp_gray.mode == "L"


def test_qfactor_mapping():
    assert _qfactor(95) == 0.1
    assert _qfactor(10) == 1.8
    assert _qfactor(90) < _qfactor(20)


def test_optimize_jpeg_quality_reduces_size(tmp_out):
    gs = find_ghostscript()
    if not gs:
        pytest.skip("Ghostscript не найден")
    big = tmp_out / "big.png"
    Image.new("RGB", (2400, 1800), (200, 100, 30)).save(big)
    raw = tmp_out / "raw.pdf"
    images_to_pdf([str(big)], str(raw))
    hi = tmp_out / "hi.pdf"
    lo = tmp_out / "lo.pdf"
    optimize_pdf(gs, str(raw), str(hi), QualitySettings(preset="custom", dpi=150, jpeg_quality=95))
    optimize_pdf(gs, str(raw), str(lo), QualitySettings(preset="custom", dpi=150, jpeg_quality=15))
    assert os.path.getsize(str(lo)) < os.path.getsize(str(hi))


def test_preview_window_updates(tmp_out):
    from app import App, PreviewWindow

    im = Image.new("RGB", (800, 600), (40, 120, 200))
    src = tmp_out / "p.jpg"
    im.save(src, quality=90)

    root = App()
    root.withdraw()
    root.files = [str(src)]
    root.open_preview()
    pw = next(w for w in root.winfo_children() if isinstance(w, PreviewWindow))
    assert pw.lbl_orig_info.cget("text") != ""
    assert "~" in pw.lbl_comp_info.cget("text")
    pw.var_gray.set(True)
    pw._update()
    assert pw.lbl_comp_info.cget("text") != ""
    pw.destroy()
    root.destroy()
