import importlib.util
from functools import partial
from pathlib import Path
from typing import Any

from ..core.errors import ConversionError, InvalidFileError
from ..core.options import Option
from ..core.registry import register_converter

# Pillow reports phone JPEGs with several frames as "MPO".
_SOURCES = {"png": {"PNG"}, "jpg": {"JPEG", "MPO"}, "webp": {"WEBP"}}
_SAVE_FORMATS = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP", "pdf": "PDF"}

_QUALITY = (
    Option("quality", "int", 85, "Output quality: higher looks better and is larger.",
           min=1, max=100),
)
_OPTIONS = {"jpg": _QUALITY, "webp": _QUALITY, "pdf": _QUALITY}

_WEBP_MAX_SIDE = 16383
_ICC_SAFE_MODES = {"RGB", "RGBA", "L", "LA", "P"}
_WIDE_GRAY_MODES = {"I", "I;16", "I;16L", "I;16B"}


def is_available() -> bool:
    """True if Pillow is installed (checked without importing it)."""
    return importlib.util.find_spec("PIL") is not None


def register() -> None:
    for source in _SOURCES:
        for target in _SAVE_FORMATS:
            if source != target:
                register_converter(
                    source, target, partial(convert_image, source, target),
                    _OPTIONS.get(target, ()), replace=True,
                )


def convert_image(source: str, target: str, src: Path, dst: Path, options: dict[str, Any]) -> None:
    """Convert between PNG, JPG and WebP, or write an image as a one-page PDF.

    Applies EXIF orientation, keeps only the first frame of animations, flattens
    transparency onto white when the target cannot store it, and drops metadata
    (EXIF, GPS, text). The ICC colour profile is kept because it changes how
    the pixels look.
    """
    img, icc_profile = _load(src, source)
    if target == "webp" and max(img.size) > _WEBP_MAX_SIDE:
        raise ConversionError(f"'{src.name}' is too large for WebP (max {_WEBP_MAX_SIDE} px per side).")
    img = _prepare(img, target)

    save_args: dict[str, Any] = {"format": _SAVE_FORMATS[target]}
    if "quality" in options:
        save_args["quality"] = options["quality"]
    if icc_profile and target != "pdf":
        save_args["icc_profile"] = icc_profile
    img.save(dst, **save_args)


def _load(src: Path, source: str) -> tuple[Any, bytes | None]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(src) as img:
            if img.format not in _SOURCES[source]:
                raise InvalidFileError(
                    f"'{src.name}' is named like a {source.upper()} image "
                    f"but its content is {img.format}."
                )
            img.load()
            icc_profile = img.info.get("icc_profile") if img.mode in _ICC_SAFE_MODES else None
            return ImageOps.exif_transpose(img), icc_profile
    except InvalidFileError:
        raise
    except UnidentifiedImageError as exc:
        raise InvalidFileError(f"'{src.name}' is not a valid image.") from exc
    except Image.DecompressionBombError as exc:
        raise InvalidFileError(f"'{src.name}' is too large to process safely.") from exc
    except MemoryError as exc:
        raise ConversionError(f"Not enough memory to convert '{src.name}'.") from exc
    except Exception as exc:
        raise InvalidFileError(f"'{src.name}' is damaged or incomplete.") from exc


def _prepare(img: Any, target: str) -> Any:
    """Bring the image into a mode the target format can store."""
    from PIL import Image

    if img.mode in _WIDE_GRAY_MODES:  # 16-bit: a plain convert("L") would clip
        img = img.point(lambda value: value * (1 / 256)).convert("L")

    if target == "png":
        return img.convert("RGB") if img.mode == "CMYK" else img

    if target == "webp":
        mode = "RGBA" if img.has_transparency_data else "RGB"
        return img if img.mode == mode else img.convert(mode)

    # JPEG and PDF have no alpha channel: flatten onto white.
    if img.has_transparency_data:
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return img if img.mode in ("RGB", "L") else img.convert("RGB")
