"""Decode image content completely; originals are never changed by this module."""
from __future__ import annotations

from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif
except ImportError:
    pillow_heif = None
else:
    pillow_heif.register_heif_opener()


class ImageCodecError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif"),
    "BMP": ("image/bmp", ".bmp"), "TIFF": ("image/tiff", ".tiff"),
    "HEIF": ("image/heif", ".heif"), "HEIC": ("image/heic", ".heic"),
    "AVIF": ("image/avif", ".avif"),
}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_FRAMES = 200
MAX_TOTAL_FRAME_PIXELS = 80_000_000


def validate_image(data: bytes, content_type: str | None = None) -> tuple[str, str, int, int]:
    if not data:
        raise ImageCodecError("image_empty", "图片文件为空")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageCodecError("image_too_large", "单张原图不能超过 25 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                detected = FORMATS.get(str(source.format).upper())
                if detected is None:
                    raise ImageCodecError("image_format_unsupported", "不支持该图片格式")
                mime, suffix = detected
                width, height = source.size
                frames = int(getattr(source, "n_frames", 1))
                if width * height > MAX_PIXELS or frames > MAX_FRAMES or width * height * frames > MAX_TOTAL_FRAME_PIXELS:
                    raise ImageCodecError("image_decode_limit", "图片像素或帧数超过安全解码限制")
                source.verify()
            # verify() alone does not decode JPEG pixels or every animation frame.
            with Image.open(BytesIO(data)) as source:
                for index in range(frames):
                    source.seek(index)
                    source.load()
    except ImageCodecError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ImageCodecError("image_decode_limit", "图片像素超过安全解码限制") from None
    except (UnidentifiedImageError, OSError, ValueError, EOFError, SyntaxError):
        heif = len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
        if heif and pillow_heif is None:
            raise ImageCodecError("image_decoder_unavailable", "未安装 HEIC/HEIF 解码器，不能确认图片完整性") from None
        raise ImageCodecError("image_corrupt", "图片文件损坏或无法完整解码") from None
    supplied = (content_type or "").split(";", 1)[0].strip().lower()
    supplied = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "image/x-png": "image/png"}.get(supplied, supplied)
    if mime in {"image/heif", "image/heic"} and supplied in {"image/heif", "image/heic"}:
        mime, suffix = supplied, ".heic" if supplied == "image/heic" else ".heif"
    if supplied and supplied not in {mime, "application/octet-stream", "binary/octet-stream"}:
        raise ImageCodecError("image_mime_mismatch", "图片格式与文件内容不一致")
    return mime, suffix, width, height


def compatible_preview(data: bytes, *, max_edge: int = 1600) -> tuple[bytes, str]:
    validate_image(data)
    with Image.open(BytesIO(data)) as original:
        original.seek(0)
        source = ImageOps.exif_transpose(original).convert("RGBA")
        source.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        # A fresh image removes EXIF and all other inherited metadata.
        output = Image.new("RGBA", source.size)
        output.paste(source)
        buffer = BytesIO()
        output.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"
