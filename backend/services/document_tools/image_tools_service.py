from __future__ import annotations

from pathlib import Path

from backend.services.document_tools.document_tool_result import DocumentToolResult
from backend.services.document_tools.safe_file_service import (
    assert_existing_file,
    build_output_path,
    file_metadata,
)

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - dependencia no instalada todavía
    Image = None
    ImageOps = None


SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def _require_pillow() -> None:
    if Image is None:
        raise RuntimeError(
            "Falta la dependencia Pillow. Instala o añade en requirements.txt: Pillow"
        )


def get_image_metadata(source_path: str | Path) -> DocumentToolResult:
    operation = "image_metadata"

    try:
        _require_pillow()
        source = assert_existing_file(source_path)

        if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        with Image.open(source) as img:
            metadata = file_metadata(source)
            metadata.update(
                {
                    "width": img.width,
                    "height": img.height,
                    "mode": img.mode,
                    "format": img.format,
                    "mime_type": Image.MIME.get(img.format, None),
                }
            )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=source,
            metadata=metadata,
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def image_to_pdf(source_path: str | Path, output_stem: str | None = None) -> DocumentToolResult:
    operation = "image_to_pdf"

    try:
        _require_pillow()
        source = assert_existing_file(source_path)

        if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        output = build_output_path(
            operation="image_to_pdf",
            source_path=source,
            extension=".pdf",
            subdir="converted",
            stem=output_stem,
        )

        with Image.open(source) as img:
            rgb = img.convert("RGB")
            rgb.save(output, "PDF", resolution=100.0)

            metadata = {
                "source_width": img.width,
                "source_height": img.height,
                "source_format": img.format,
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            }

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata=metadata,
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def images_to_pdf(source_paths: list[str | Path], output_stem: str | None = None) -> DocumentToolResult:
    operation = "images_to_pdf"
    output = None

    try:
        _require_pillow()

        if not source_paths:
            raise ValueError("Debe indicarse al menos una imagen.")

        sources = [assert_existing_file(path) for path in source_paths]

        for source in sources:
            if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        output = build_output_path(
            operation="images_to_pdf",
            extension=".pdf",
            subdir="converted",
            stem=output_stem or "imagenes_unidas",
        )

        opened_images = []
        rgb_images = []

        try:
            for source in sources:
                img = Image.open(source)
                opened_images.append(img)
                rgb_images.append(img.convert("RGB"))

            first, rest = rgb_images[0], rgb_images[1:]
            first.save(output, "PDF", save_all=True, append_images=rest, resolution=100.0)

        finally:
            for img in opened_images:
                img.close()

        return DocumentToolResult.success(
            operation=operation,
            source_paths=sources,
            output_path=output,
            metadata={
                "source_count": len(sources),
                "page_count": len(sources),
                "mime_type": "application/pdf",
                "size_bytes": output.stat().st_size,
            },
        )

    except Exception as exc:
        # A partially written PDF is never left behind as if it were a result.
        if output is not None:
            Path(output).unlink(missing_ok=True)
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=source_paths,
            errors=[str(exc)],
        )

def crop_image(
    source_path: str | Path,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    output_stem: str | None = None,
) -> DocumentToolResult:
    operation = "image_crop"

    try:
        _require_pillow()
        source = assert_existing_file(source_path)

        if source.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            raise ValueError(f"Formato de imagen no soportado: {source.suffix}")

        with Image.open(source) as img:
            width, height = img.size

            left_i = int(left)
            top_i = int(top)
            right_i = int(right)
            bottom_i = int(bottom)

            if left_i < 0 or top_i < 0 or right_i > width or bottom_i > height:
                raise ValueError(
                    f"Recorte fuera de límites. Imagen={width}x{height}, "
                    f"crop={(left_i, top_i, right_i, bottom_i)}"
                )

            if left_i >= right_i or top_i >= bottom_i:
                raise ValueError(
                    f"Coordenadas inválidas de recorte: "
                    f"{(left_i, top_i, right_i, bottom_i)}"
                )

            cropped = img.crop((left_i, top_i, right_i, bottom_i))

            extension = source.suffix.lower() or ".png"
            output = build_output_path(
                operation="crop",
                source_path=source,
                extension=extension,
                subdir="images",
                stem=output_stem,
            )

            if extension in {".jpg", ".jpeg"} and cropped.mode not in ("RGB", "L"):
                cropped = cropped.convert("RGB")

            cropped.save(output)

            metadata = {
                "source_width": width,
                "source_height": height,
                "output_width": cropped.width,
                "output_height": cropped.height,
                "crop_box": [left_i, top_i, right_i, bottom_i],
                "source_format": img.format,
                "mime_type": Image.MIME.get(img.format, None),
                "size_bytes": output.stat().st_size,
            }

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata=metadata,
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


# --------------------------------------------------------------------------- JPG/PNG editing (DV29)
#
# Rotation, proportional resize, optimization and JPG<->PNG conversion. Only
# JPG/JPEG/PNG whose real content matches the extension are accepted. The EXIF
# orientation is applied before any transformation, so every derivative looks
# like the image shown in the viewer and carries no orientation tag. Alpha is
# kept in PNG and flattened on JPEG_BACKGROUND for JPG. The source is only
# read; derivatives are created exclusively (never overwritten).

EDITABLE_IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png"}
FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png"}

MAX_EDITABLE_IMAGE_BYTES = 40 * 1024 * 1024
MAX_EDITABLE_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_SIDE = 12_000

JPEG_QUALITY_RANGE = (30, 95)
DEFAULT_JPEG_QUALITY = 80
DERIVED_JPEG_QUALITY = 95
JPEG_BACKGROUND = (255, 255, 255)
JPEG_BACKGROUND_HEX = "#FFFFFF"

EXIF_ORIENTATION_TAG = 0x0112


class ImageValidationError(ValueError):
    """The image or a parameter is not acceptable; message is user-facing."""


def _check_dimensions(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise ImageValidationError(f"Dimensiones de imagen no válidas: {width}x{height}.")
    if max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_EDITABLE_IMAGE_PIXELS:
        raise ImageValidationError(
            f"Imagen demasiado grande: {width}x{height} px. Máximo {MAX_IMAGE_SIDE} px por lado "
            f"y {MAX_EDITABLE_IMAGE_PIXELS} píxeles en total."
        )


def _has_alpha(img) -> bool:
    return img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in img.info


def _flatten_on_background(img):
    rgba = img.convert("RGBA")
    base = Image.new("RGB", rgba.size, JPEG_BACKGROUND)
    base.paste(rgba, mask=rgba.getchannel("A"))
    if img.info.get("icc_profile"):
        base.info["icc_profile"] = img.info["icc_profile"]
    return base


def _prepare_for(img, fmt: str):
    """(image ready to be encoded as fmt, alpha_flattened)."""
    if fmt == "JPEG":
        if _has_alpha(img):
            return _flatten_on_background(img), True
        if img.mode not in ("RGB", "L", "CMYK"):
            return img.convert("RGB"), False
        return img, False
    if img.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"):
        return img.convert("RGBA" if _has_alpha(img) else "RGB"), False
    return img, False


def _encode_params(img, fmt: str, *, quality: int = DERIVED_JPEG_QUALITY, optimize: bool = False) -> dict:
    params = {}
    if img.info.get("icc_profile"):
        params["icc_profile"] = img.info["icc_profile"]
    if fmt == "JPEG":
        params.update(quality=int(quality), optimize=bool(optimize))
        if optimize:
            params["progressive"] = True
    elif optimize:
        params["optimize"] = True  # zlib level 9: lossless
    return params


def _write_exclusive(img, output: Path, fmt: str, **params) -> Path:
    """Encode into a file that must not exist yet; a partial file is removed."""
    output = Path(output)
    handle = output.open("xb")  # FileExistsError: an existing file is never touched
    try:
        with handle:
            img.save(handle, format=fmt, **params)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def _derived_output(source: Path, operation: str, extension: str, stem: str | None, subdir: str = "images") -> Path:
    output = build_output_path(
        operation=operation,
        source_path=source,
        extension=extension,
        subdir=subdir,
        stem=stem,
    )
    if output.resolve() == source.resolve() or output.exists():
        raise ImageValidationError("La ruta del derivado coincide con un archivo existente; no se sobrescribe.")
    return output


def _int_value(value, label: str) -> int:
    if isinstance(value, bool):
        raise ImageValidationError(f"{label}: escribe un número entero.")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ImageValidationError(f"{label}: escribe un número entero.") from exc


def _optional_side(value, label: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    side = _int_value(value, label)
    if side < 1 or side > MAX_IMAGE_SIDE:
        raise ImageValidationError(f"{label} fuera de límites: debe estar entre 1 y {MAX_IMAGE_SIDE} px.")
    return side


def open_editable_image(source_path: str | Path):
    """(image, details) for a valid JPG/JPEG/PNG; the file is only read.

    The image is fully decoded (corrupt or truncated files are refused) and
    returned with its EXIF orientation already applied. The caller closes it.
    """
    _require_pillow()
    source = assert_existing_file(source_path)
    expected = EDITABLE_IMAGE_FORMATS.get(source.suffix.lower())
    if expected is None:
        raise ImageValidationError(
            f"Formato no admitido: {source.suffix or 'sin extensión'}. Solo JPG, JPEG o PNG."
        )
    size_bytes = source.stat().st_size
    if size_bytes == 0:
        raise ImageValidationError("El archivo de imagen está vacío.")
    if size_bytes > MAX_EDITABLE_IMAGE_BYTES:
        raise ImageValidationError(
            f"Imagen demasiado pesada: {size_bytes / 1048576:.1f} MB. "
            f"Máximo {MAX_EDITABLE_IMAGE_BYTES // 1048576} MB."
        )

    try:
        with Image.open(source) as img:
            if img.format != expected:
                raise ImageValidationError(
                    f"El contenido real ({img.format or 'desconocido'}) no coincide con la extensión "
                    f"{source.suffix}."
                )
            if getattr(img, "n_frames", 1) > 1:
                raise ImageValidationError("Imagen animada o multipágina: no se puede procesar.")
            _check_dimensions(img.width, img.height)
            img.load()
            try:
                orientation = int(img.getexif().get(EXIF_ORIENTATION_TAG, 1) or 1)
            except Exception:
                orientation = 1
            stored_size = img.size
            oriented = ImageOps.exif_transpose(img)
    except ImageValidationError:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageValidationError(f"Imagen demasiado grande: {exc}") from exc
    except Exception as exc:
        raise ImageValidationError(f"La imagen está dañada o no se puede leer: {exc}") from exc

    details = {
        "source_format": expected,
        "source_mode": oriented.mode,
        "source_size_bytes": size_bytes,
        "source_stored_width": stored_size[0],
        "source_stored_height": stored_size[1],
        "source_width": oriented.width,
        "source_height": oriented.height,
        "exif_orientation": orientation if 1 <= orientation <= 8 else 1,
        "has_alpha": _has_alpha(oriented),
    }
    return oriented, details


def oriented_working_copy(source_path: str | Path, *, flatten_alpha: bool = False) -> Path | None:
    """Temporary EXIF-oriented copy (alpha flattened on white when asked) for the
    engines that read raw pixels (crop_image, image_to_pdf).

    None when the source can be used as is. The caller deletes the copy.
    """
    source = assert_existing_file(source_path)
    img, details = open_editable_image(source)
    with img:
        flatten = flatten_alpha and details["has_alpha"]
        if details["exif_orientation"] == 1 and not flatten:
            return None
        fmt = details["source_format"]
        work = _flatten_on_background(img) if flatten else img
        work, _ = _prepare_for(work, fmt)
        output = _derived_output(source, "work", source.suffix.lower(), None, subdir="temp")
        _write_exclusive(work, output, fmt, **_encode_params(work, fmt))
    return output


def _derive_image(operation: str, short_name: str, source_path, transform, output_stem: str | None):
    """Open, transform and write a new derivative.

    transform(img, details) -> (image, format, encode kwargs, extra metadata).
    """
    try:
        source = assert_existing_file(source_path)
        img, details = open_editable_image(source)
        with img:
            produced, fmt, encode, extra = transform(img, details)
            produced, flattened = _prepare_for(produced, fmt)
            _check_dimensions(produced.width, produced.height)
            extension = (source.suffix.lower() if fmt == details["source_format"]
                         else FORMAT_EXTENSIONS[fmt])
            output = _derived_output(source, short_name, extension, output_stem)
            _write_exclusive(produced, output, fmt, **_encode_params(produced, fmt, **encode))

            metadata = dict(details)
            metadata.update(extra)
            metadata.update(
                {
                    "output_width": produced.width,
                    "output_height": produced.height,
                    "output_format": fmt,
                    "output_has_alpha": _has_alpha(produced),
                    "alpha_flattened": flattened,
                    "background": JPEG_BACKGROUND_HEX if flattened else None,
                    "exif_orientation_applied": details["exif_orientation"] != 1,
                    "mime_type": FORMAT_MIME[fmt],
                    "size_bytes": output.stat().st_size,
                }
            )

        return DocumentToolResult.success(
            operation=operation,
            source_paths=[source],
            output_path=output,
            metadata=metadata,
        )

    except Exception as exc:
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=[str(exc)],
        )


def rotate_image(source_path: str | Path, *, degrees: int, output_stem: str | None = None) -> DocumentToolResult:
    """Clockwise rotation by 90, 180 or 270 degrees (pixel transposition)."""

    def transform(img, details):
        value = _int_value(degrees, "Grados")
        if value not in (90, 180, 270):
            raise ImageValidationError("Rotación no válida: usa 90, 180 o 270 grados.")
        method = {
            90: Image.Transpose.ROTATE_270,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }[value]
        return img.transpose(method), details["source_format"], {}, {"degrees": value, "direction": "clockwise"}

    return _derive_image("image_rotate", "rotate", source_path, transform, output_stem)


def resize_image(
    source_path: str | Path,
    *,
    width: int | None = None,
    height: int | None = None,
    output_stem: str | None = None,
) -> DocumentToolResult:
    """Proportional resize (LANCZOS) to fit within width and/or height."""

    def transform(img, details):
        target_w = _optional_side(width, "Ancho")
        target_h = _optional_side(height, "Alto")
        if target_w is None and target_h is None:
            raise ImageValidationError("Indica el ancho, el alto o ambos.")
        w, h = img.size
        scale = min(s for s in (target_w and target_w / w, target_h and target_h / h) if s)
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        _check_dimensions(*new_size)
        if new_size == (w, h):
            raise ImageValidationError("La imagen ya tiene ese tamaño; no se genera copia.")
        work = img
        if img.mode in ("1", "P"):  # LANCZOS needs a continuous mode
            work = img.convert("RGBA" if _has_alpha(img) else "RGB")
        resized = work.resize(new_size, Image.Resampling.LANCZOS)
        return resized, details["source_format"], {}, {
            "requested_width": target_w,
            "requested_height": target_h,
            "resample": "LANCZOS",
        }

    return _derive_image("image_resize", "resize", source_path, transform, output_stem)


def optimize_image(
    source_path: str | Path,
    *,
    quality: int | None = None,
    output_stem: str | None = None,
) -> DocumentToolResult:
    """JPG: re-encode with bounded quality. PNG: lossless recompression.

    A result that is not smaller than the source is discarded and reported.
    """
    operation = "image_optimize"

    def transform(img, details):
        if details["source_format"] == "JPEG":
            value = DEFAULT_JPEG_QUALITY if quality in (None, "") else _int_value(quality, "Calidad")
            low, high = JPEG_QUALITY_RANGE
            if not low <= value <= high:
                raise ImageValidationError(f"Calidad fuera de límites: debe estar entre {low} y {high}.")
            return img, "JPEG", {"quality": value, "optimize": True}, {"quality": value, "lossless": False}
        if quality not in (None, ""):
            raise ImageValidationError("La optimización PNG es sin pérdida: no admite calidad.")
        return img, "PNG", {"optimize": True}, {"quality": None, "lossless": True}

    result = _derive_image(operation, "optimize", source_path, transform, output_stem)
    if result.ok and result.metadata["size_bytes"] >= result.metadata["source_size_bytes"]:
        Path(result.output_path).unlink(missing_ok=True)
        return DocumentToolResult.failure(
            operation=operation,
            source_paths=[source_path],
            errors=["La optimización no reduce el tamaño del archivo; no se genera copia."],
        )
    return result


def convert_image_format(
    source_path: str | Path,
    *,
    target_format: str,
    output_stem: str | None = None,
) -> DocumentToolResult:
    """JPG -> PNG (lossless) or PNG -> JPG (alpha flattened on white)."""

    def transform(img, details):
        target = str(target_format or "").strip().lower().lstrip(".")
        fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}.get(target)
        if fmt is None:
            raise ImageValidationError("Formato de destino no válido: usa JPG o PNG.")
        if fmt == details["source_format"]:
            raise ImageValidationError(f"La imagen ya está en formato {target.upper()}.")
        return img, fmt, {}, {"target_format": fmt}

    return _derive_image("image_convert", "convert", source_path, transform, output_stem)

