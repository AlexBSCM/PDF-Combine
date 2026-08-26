"""Автоустановка Ghostscript: скачивает официальный инсталлятор с GitHub
Releases Artifex и запускает его в тихом режиме."""
import json
import os
import re
import subprocess
import tempfile
import urllib.request

from gs_locator import find_ghostscript

RELEASES_API = (
    "https://api.github.com/repos/ArtifexSoftware/ghostpdl-downloads/releases?per_page=5"
)
_USER_AGENT = "pdfconv-autoinstaller"


def pick_installer_asset(assets: list[dict]) -> dict | None:
    """Выбирает ассет вида gsNNNNw64.exe из списка ассетов релиза."""
    for asset in assets:
        name = asset.get("name", "")
        if re.fullmatch(r"gs\d+w64\.exe", name):
            return asset
    return None


def fetch_latest_installer_url(timeout: int = 30) -> tuple[str, str] | None:
    """Возвращает (url_инсталлятора, тег_релиза) либо None."""
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        releases = json.loads(response.read().decode("utf-8"))
    for release in releases:
        asset = pick_installer_asset(release.get("assets", []))
        if asset and asset.get("browser_download_url"):
            return asset["browser_download_url"], release.get("tag_name", "?")
    return None


def download(url: str, dst: str, progress_cb=None) -> None:
    def hook(blocks: int, block_size: int, total: int):
        if progress_cb and total > 0:
            done = min(blocks * block_size, total)
            progress_cb(int(done * 100 / total))

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, open(dst, "wb") as f:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            received += len(chunk)
            if progress_cb and total > 0:
                progress_cb(min(100, int(received * 100 / total)))


def install_ghostscript(progress_cb=None, status_cb=None) -> str | None:
    """Гарантирует наличие Ghostscript; при отсутствии скачивает и ставит.

    Возвращает путь к gswin64c.exe или None при неудаче.
    Во время тихой установки Windows покажет один запрос UAC.
    """
    existing = find_ghostscript()
    if existing:
        return existing

    info = fetch_latest_installer_url()
    if not info:
        raise RuntimeError("Не удалось получить список релизов Ghostscript")
    url, tag = info
    if status_cb:
        status_cb(f"Скачиваю Ghostscript {tag}...")

    tmp_dir = tempfile.mkdtemp(prefix="pdfconv_gs_")
    installer = os.path.join(tmp_dir, "gs_setup.exe")
    try:
        download(url, installer, progress_cb=progress_cb)
        if status_cb:
            status_cb("Запускаю установку (подтвердите запрос Windows/UAC)...")
        result = subprocess.run(
            [installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            timeout=900,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Инсталлятор вернул код {result.returncode}")
    finally:
        try:
            os.remove(installer)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    found = find_ghostscript()
    if not found:
        raise RuntimeError("После установки Ghostscript не найден")
    return found
