"""Raw-конвертация изображений (jpg/png/bmp/webp) в PDF.

В custom-режиме (dpi + jpeg_quality заданы) изображения сразу сжимаются
через Pillow — ровно как в окне предпросмотра (WYSIWYG). Иначе собираются
в PDF без потерь, а сжатие потом делает Ghostscript.
"""
import os
import shutil
import tempfile

import img2pdf
from PIL import Image, ImageOps

from converters.preview import compress_to_bytes

_ALPHA_MODES = {"RGBA", "LA", "PA", "RGBa"}


def images_to_pdf(
    image_paths: list[str],
    output_path: str,
    work_dir: str | None = None,
    dpi: int | None = None,
    jpeg_quality: int | None = None,
    grayscale: bool = False,
) -> None:
    """Собирает список изображений в один PDF (каждое изображение = страница).

    Если заданы dpi и jpeg_quality — изображения сжимаются через Pillow сразу.
    Иначе img2pdf собирает без потерь (альфа-канал на белый фон), а сжатие
    выполняется позже через Ghostscript.
    """
    if dpi is not None and jpeg_quality is not None:
        raws = [compress_to_bytes(p, dpi, jpeg_quality, grayscale) for p in image_paths]
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(raws, rotation=img2pdf.Rotation.ifvalid))
        return

    own_dir = work_dir is None
    work = work_dir or tempfile.mkdtemp(prefix="pdfconv_img_")
    try:
        prepared = [
            _prepare_image(path, os.path.join(work, f"prep_{i}.png"))
            for i, path in enumerate(image_paths)
        ]
        with open(output_path, "wb") as f:
            f.write(img2pdf.convert(prepared, rotation=img2pdf.Rotation.ifvalid))
    finally:
        if own_dir:
            shutil.rmtree(work, ignore_errors=True)


def _prepare_image(path: str, flat_path: str) -> str:
    try:
        with Image.open(path) as im:
            has_alpha = im.mode in _ALPHA_MODES or (
                im.mode == "P" and "transparency" in im.info
            )
            if not has_alpha:
                return path
            im = ImageOps.exif_transpose(im)
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.getchannel("A"))
            bg.save(flat_path)
            return flat_path
    except Exception:
        return path
