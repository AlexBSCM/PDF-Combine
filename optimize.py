"""Оптимизация (пересжатие) PDF через Ghostscript."""
import subprocess
from dataclasses import dataclass


@dataclass
class QualitySettings:
    preset: str = "ebook"  # screen | ebook | printer | prepress | custom
    dpi: int = 150          # используется только при preset == "custom"
    grayscale: bool = False


def optimize_pdf(gs_path: str, input_path: str, output_path: str, settings: QualitySettings) -> None:
    """Пересжимает input_path -> output_path согласно настройкам качества."""
    args = [
        gs_path,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
    ]

    if settings.preset in ("screen", "ebook", "printer", "prepress"):
        args.append(f"-dPDFSETTINGS=/{settings.preset}")
    else:
        # custom: собственный DPI для изображений
        dpi = str(settings.dpi)
        args += [
            "-dDownsampleColorImages=true",
            f"-dColorImageResolution={dpi}",
            "-dDownsampleGrayImages=true",
            f"-dGrayImageResolution={dpi}",
            "-dDownsampleMonoImages=true",
            f"-dMonoImageResolution={dpi}",
            "-dColorImageDownsampleType=/Bicubic",
            "-dGrayImageDownsampleType=/Bicubic",
        ]

    if settings.grayscale:
        args += [
            "-sColorConversionStrategy=Gray",
            "-dProcessColorModel=/DeviceGray",
        ]

    args += [f"-sOutputFile={output_path}", input_path]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Ghostscript завершился с ошибкой:\n{result.stderr}")
