"""Поиск исполняемого файла Ghostscript (gswin64c.exe / gswin32c.exe) на Windows."""
import glob
import os
import shutil


def find_ghostscript() -> str | None:
    """Возвращает путь к gswin64c.exe/gswin32c.exe, либо None если не найден."""
    for name in ("gswin64c", "gswin32c", "gs"):
        found = shutil.which(name)
        if found:
            return found

    program_files_dirs = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for pf in program_files_dirs:
        if not pf:
            continue
        pattern = os.path.join(pf, "gs", "gs*", "bin", "gswin64c.exe")
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
        pattern32 = os.path.join(pf, "gs", "gs*", "bin", "gswin32c.exe")
        matches32 = sorted(glob.glob(pattern32), reverse=True)
        if matches32:
            return matches32[0]

    return None
