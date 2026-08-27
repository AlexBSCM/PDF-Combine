"""Живой предпросмотр сжатия изображения (Pillow, без Ghostscript).

Оценивает, как картинка будет выглядеть и сколько весить после даунсемплинга
до заданного DPI и JPEG-сжатия. Та же логика используется и при реальной
сборке PDF из изображений, поэтому предпросмотр — это WYSIWYG.
"""
import io

from PIL import Image, ImageOps

A4_WIDTH_IN = 8.27


def _downscale(im: Image.Image, dpi: int) -> Image.Image:
    target_w = max(1, int(A4_WIDTH_IN * max(10, dpi)))
    if im.width > target_w:
        target_h = max(1, round(im.height * target_w / im.width))
        return im.resize((target_w, target_h), Image.LANCZOS)
    return im


def _flatten_alpha(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode == "P":
        return im.convert("RGB")
    if im.mode not in ("RGB", "L"):
        return im.convert("RGB")
    return im


def compress_to_bytes(source_path: str, dpi: int, quality: int, grayscale: bool) -> bytes:
    """Возвращает сжатые JPEG-байты (без альфа, даунсемплинг по DPI)."""
    q = max(10, min(95, int(quality)))
    with Image.open(source_path) as im:
        im = ImageOps.exif_transpose(im)
        im = _flatten_alpha(im)
        if grayscale and im.mode != "L":
            im = im.convert("L")
        im = _downscale(im, dpi)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=q, optimize=True)
        return buf.getvalue()


def render_compressed(
    source_path: str, dpi: int, quality: int, grayscale: bool
) -> tuple[Image.Image, int]:
    """Возвращает (сжатое изображение, размер JPEG в байтах) — для предпросмотра."""
    data = compress_to_bytes(source_path, dpi, quality, grayscale)
    im = Image.open(io.BytesIO(data)).copy()
    return im, len(data)
