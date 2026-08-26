"""Живой предпросмотр сжатия изображения (Pillow, без Ghostscript).

Оценивает, как картинка будет выглядеть и сколько весить после даунсемплинга
до заданного DPI и JPEG-сжатия — теми же принципами, что действует
Ghostscript в custom-режиме.
"""
import io

from PIL import Image, ImageOps

A4_WIDTH_IN = 8.27


def render_compressed(
    source_path: str, dpi: int, quality: int, grayscale: bool
) -> tuple[Image.Image, int]:
    """Возвращает (сжатое изображение, размер JPEG в байтах)."""
    with Image.open(source_path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        target_w = max(1, int(A4_WIDTH_IN * max(10, dpi)))
        if im.width > target_w:
            target_h = max(1, round(im.height * target_w / im.width))
            im = im.resize((target_w, target_h), Image.LANCZOS)
        if grayscale and im.mode != "L":
            im = im.convert("L")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=max(10, min(95, quality)), optimize=True)
        return im, buf.tell()
