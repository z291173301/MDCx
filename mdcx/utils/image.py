"""Helpers for normalizing downloaded image files."""

from __future__ import annotations

import asyncio
import os
from io import BytesIO
from pathlib import Path

from PIL import Image

MAX_IMAGE_DIMENSION = 1100
IMAGE_QUALITY = 80

_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}
IMAGE_SUFFIXES = frozenset(_FORMAT_BY_SUFFIX)


def _resize_to_max_dimension(image: Image.Image, max_dimension: int) -> Image.Image:
    width, height = image.size
    current_max_dimension = max(width, height)
    if current_max_dimension <= max_dimension:
        return image

    scale = max_dimension / current_max_dimension
    return image.resize(
        (max(round(width * scale), 1), max(round(height * scale), 1)),
        resample=Image.Resampling.LANCZOS,
    )


def _encode_image(image: Image.Image, save_format: str, quality: int = IMAGE_QUALITY) -> bytes:
    output = BytesIO()
    save_kwargs: dict[str, object] = {"format": save_format}
    if save_format in {"JPEG", "WEBP"}:
        save_kwargs["quality"] = quality
        if save_format == "JPEG":
            save_kwargs["optimize"] = True
    else:
        # PNG 无损压缩：9 级与 6 级压缩比差异极小但耗时数倍，用 PIL 默认 6 提速
        save_kwargs.update({"optimize": True, "compress_level": 6})
    image.save(output, **save_kwargs)  # type: ignore[arg-type]
    return output.getvalue()


def compress_image(file_path: Path, enabled: bool = True) -> bool:
    """Compress a downloaded image and scale oversized images in place."""
    if not enabled:
        return False

    temp_path = file_path.with_name(f"{file_path.stem}.[COMPRESS]{file_path.suffix}")
    resized_image = None
    converted_image = None

    try:
        with Image.open(file_path) as image:
            image.load()
            if getattr(image, "is_animated", False):
                return False

            save_format = _FORMAT_BY_SUFFIX.get(file_path.suffix.lower(), image.format)
            if save_format not in {"JPEG", "PNG", "WEBP"}:
                return False

            source_image: Image.Image = image
            if save_format == "JPEG" and source_image.mode not in {"RGB", "L"}:
                converted_image = source_image.convert("RGB")
                source_image = converted_image

            resized_image = _resize_to_max_dimension(source_image, MAX_IMAGE_DIMENSION)
            encoded = _encode_image(resized_image, save_format)

            temp_path.write_bytes(encoded)

        os.replace(temp_path, file_path)
        return True
    except Exception:
        return False
    finally:
        if resized_image is not None:
            resized_image.close()
        if converted_image is not None:
            converted_image.close()
        temp_path.unlink(missing_ok=True)


async def compress_image_async(file_path: Path, enabled: bool = True) -> bool:
    """Run image compression off the event loop."""
    return await asyncio.to_thread(compress_image, file_path, enabled)


async def compress_images_in_folder_async(folder_path: Path, enabled: bool = True) -> None:
    """Compress the final image files in an output folder."""
    if not enabled or not folder_path.is_dir():
        return

    image_paths = [
        path
        for path in folder_path.rglob("*")
        if not path.is_symlink() and path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    sem = asyncio.Semaphore(8)

    async def _limited(path):
        async with sem:
            await compress_image_async(path, True)

    await asyncio.gather(*(_limited(path) for path in image_paths))
