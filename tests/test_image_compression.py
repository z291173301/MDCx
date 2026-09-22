from pathlib import Path

import pytest
from PIL import Image

import mdcx.base.image as base_image
import mdcx.base.web as base_web
from mdcx.config.enums import FixedScrapingType
from mdcx.config.manager import manager
from mdcx.core.image import cut_thumb_to_poster
from mdcx.models.model_types import CrawlersResult
from mdcx.utils.image import compress_image, compress_images_in_folder_async


def _save_jpeg(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, "white").save(path, format="JPEG", quality=95)


def test_compress_image_scales_when_either_dimension_exceeds_limit(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    _save_jpeg(image_path, (2000, 1000))

    assert compress_image(image_path) is True

    with Image.open(image_path) as image:
        assert image.size == (1100, 550)
        assert image.format == "JPEG"


def test_compress_image_keeps_dimensions_below_limit(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    _save_jpeg(image_path, (1099, 800))

    assert compress_image(image_path) is True

    with Image.open(image_path) as image:
        assert image.size == (1099, 800)


def test_compress_image_scales_exact_limit_below_limit(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    _save_jpeg(image_path, (1100, 800))

    assert compress_image(image_path) is True

    with Image.open(image_path) as image:
        assert image.size == (1100, 800)


def test_compress_image_scales_exactly_above_limit(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    _save_jpeg(image_path, (1101, 800))

    assert compress_image(image_path) is True

    with Image.open(image_path) as image:
        assert image.size == (1100, 799)


def test_compress_image_preserves_png_transparency(tmp_path: Path):
    image_path = tmp_path / "poster.png"
    source = Image.new("RGBA", (1600, 800), (255, 0, 0, 128))
    source.save(image_path, format="PNG")
    source.close()

    assert compress_image(image_path) is True

    with Image.open(image_path) as image:
        assert image.size == (1100, 550)
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0)) == (255, 0, 0, 128)


def test_compress_image_uses_jpeg_quality_80(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    source = Image.effect_noise((1000, 1000), 100)
    source.save(image_path, format="JPEG", quality=95)
    source.close()
    original_size = image_path.stat().st_size

    assert compress_image(image_path) is True

    assert image_path.stat().st_size < original_size


def test_compress_image_skips_non_image_files(tmp_path: Path):
    file_path = tmp_path / "trailer.mp4"
    original_content = b"not an image"
    file_path.write_bytes(original_content)

    assert compress_image(file_path) is False
    assert file_path.read_bytes() == original_content


def test_compress_image_can_be_disabled(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    _save_jpeg(image_path, (2000, 1000))

    assert compress_image(image_path, enabled=False) is False

    with Image.open(image_path) as image:
        assert image.size == (2000, 1000)


@pytest.mark.asyncio
async def test_download_file_with_filepath_defers_compression_to_final_step(tmp_path: Path, monkeypatch):
    async def fake_download(_url: str, file_path: Path, **_kwargs):
        _save_jpeg(file_path, (2000, 1000))
        return True

    monkeypatch.setattr(manager.computed.async_client, "download", fake_download)

    assert (
        await base_web.download_file_with_filepath(
            "https://example.test/poster.jpg",
            tmp_path / "poster.jpg",
            tmp_path,
        )
        is True
    )

    with Image.open(tmp_path / "poster.jpg") as image:
        assert image.size == (2000, 1000)


@pytest.mark.asyncio
async def test_compress_images_in_folder_compresses_final_output(tmp_path: Path):
    image_path = tmp_path / "poster.jpg"
    _save_jpeg(image_path, (2000, 1000))

    await compress_images_in_folder_async(tmp_path)

    with Image.open(image_path) as image:
        assert image.size == (1100, 550)


@pytest.mark.asyncio
async def test_watermark_postprocessing_does_not_trigger_another_compression(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "poster.jpg"
    source = Image.effect_noise((1100, 777), 100)
    source.save(image_path, format="JPEG", quality=80)
    source.close()

    async def fake_add_to_pic(path, image, *_args):
        temp_path = path.with_suffix(".[MARK].jpg")
        image.convert("RGB").save(temp_path, format="JPEG", quality=95, subsampling=0)
        temp_path.replace(path)

    monkeypatch.setattr(base_image, "_add_to_pic", fake_add_to_pic)

    await base_image.add_mark_thread(image_path, ["4K"])

    assert image_path.exists()


def test_cropped_poster_postprocessing_does_not_trigger_another_compression(tmp_path: Path):
    thumb_path = tmp_path / "thumb.jpg"
    poster_path = tmp_path / "poster.jpg"
    source = Image.effect_noise((1600, 900), 100)
    source.save(thumb_path, format="JPEG", quality=95)
    source.close()

    result = CrawlersResult.empty()
    assert cut_thumb_to_poster(result, thumb_path, poster_path, FixedScrapingType.YOUMA) is True

    with Image.open(poster_path) as image:
        assert image.size == (758, 900)
