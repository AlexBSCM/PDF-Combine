"""HTML -> PDF через headless Microsoft Edge / Google Chrome."""
import os
import shutil
import subprocess


def find_browser() -> str | None:
    """Возвращает путь к msedge.exe / chrome.exe либо None."""
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def html_to_pdf(input_path: str, output_path: str, browser_path: str | None = None) -> None:
    browser = browser_path or find_browser()
    if not browser:
        raise RuntimeError("Не найден Edge/Chrome — конвертация HTML недоступна")

    url = "file:///" + os.path.abspath(input_path).replace("\\", "/")
    tmp_out = output_path + ".tmp.pdf"
    args = [
        browser,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={tmp_out}",
        url,
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("Браузер не ответил за 120 секунд") from e

    if not os.path.exists(tmp_out):
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"Браузер не создал PDF:\n{stderr[:500]}")
    shutil.move(tmp_out, output_path)
