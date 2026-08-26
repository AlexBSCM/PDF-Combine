"""Оптимизация (пересжатие) PDF через Ghostscript."""
import subprocess
from dataclasses import dataclass


@dataclass
class QualitySettings:
    preset: str = "ebook"  # screen | ebook | printer | prepress | custom
    dpi: int = 150          # используется только при preset == "custom"
    grayscale: bool = False
    jpeg_quality: int = 75  # 10..95, используется только при preset == "custom"


def _qfactor(jpeg_quality: int) -> float:
    """JPEG quality 10..95 -> Distiller QFactor 1.8..0.1 (меньше = лучше)."""
    q = (100 - max(10, min(95, int(jpeg_quality)))) / 50
    return round(max(0.1, min(1.8, q)), 2)


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
        # custom: собственный DPI и JPEG-качество для изображений
        dpi = str(settings.dpi)
        q = _qfactor(settings.jpeg_quality)
        args += [
            "-dDownsampleColorImages=true",
            f"-dColorImageResolution={dpi}",
            "-dDownsampleGrayImages=true",
            f"-dGrayImageResolution={dpi}",
            "-dDownsampleMonoImages=true",
            f"-dMonoImageResolution={dpi}",
            "-dColorImageDownsampleType=/Bicubic",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dAutoFilterColorImages=false",
            "-dAutoFilterGrayImages=false",
            "-dColorImageFilter=/DCTEncode",
            "-dGrayImageFilter=/DCTEncode",
        ]

    if settings.grayscale:
        args += [
            "-sColorConversionStrategy=Gray",
            "-dProcessColorModel=/DeviceGray",
        ]

    args += [f"-sOutputFile={output_path}"]

    if settings.preset == "custom":
        q = _qfactor(settings.jpeg_quality)
        args += [
            "-c",
            (
                f"<< /ColorImageDict << /QFactor {q} /HSamples [1 1 1 1] "
                f"/VSamples [1 1 1 1] >> /GrayImageDict << /QFactor {q} "
                f"/HSamples [1 1 1 1] /VSamples [1 1 1 1] >> >> setdistillerparams"
            ),
            "-f",
        ]

    args += [input_path]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Ghostscript завершился с ошибкой:\n{result.stderr}")
