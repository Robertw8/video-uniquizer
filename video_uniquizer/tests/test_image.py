"""Unit tests for ImageProcessor orchestration and output protection."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from core.image import (
    ImageInspectionError,
    ImageProcessingError,
    ImageProcessor,
    UnsupportedImageFormatError,
    get_image_info,
)
from models.profile import ImageProcessingProfile

BASE_PROFILE = ImageProcessingProfile(
    device_model="iPhone 14 Pro",
    creation_date=datetime(2026, 8, 9, 5, 59, 11),
    brightness=1.02,
    contrast=1.03,
    saturation=0.98,
    sharpness=0.36,
    noise_level=2,
    jpeg_quality=92,
    zoom_percent=1,
)


def _pattern(width: int, height: int, *, alpha: bool = False) -> Image.Image:
    y, x = np.indices((height, width))
    rgb = np.stack((x * 5, y * 7, (x + y) * 3), axis=2)
    rgb = np.mod(rgb, 256).astype(np.uint8)
    if not alpha:
        return Image.fromarray(rgb)
    alpha_values = np.linspace(0, 255, width, dtype=np.uint8)
    alpha_channel = np.broadcast_to(alpha_values, (height, width))
    return Image.fromarray(np.dstack((rgb, alpha_channel)))


def _processor(metadata_service: Mock | None = None) -> ImageProcessor:
    return ImageProcessor(
        metadata_service=metadata_service or Mock(),
        noise_rng=np.random.default_rng(42),
    )


@pytest.mark.parametrize("suffix", (".jpg", ".jpeg"))
def test_processes_jpeg_and_jpg_alias(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "input.jpg"
    output = tmp_path / f"output{suffix}"
    exif = Image.Exif()
    exif[315] = "Legacy Artist"
    _pattern(180, 320).save(source, exif=exif)
    metadata = Mock()

    result = _processor(metadata).process(source, output, BASE_PROFILE)

    with Image.open(output) as processed:
        processed.verify()
    with Image.open(output) as processed:
        assert processed.format == "JPEG"
        assert processed.mode == "RGB"
        assert processed.size == (180, 320)
        assert not processed.info.get("progressive", False)
        assert len(processed.getexif()) == 0
    assert result.output_format == "JPEG"
    assert result.width == 180 and result.height == 320
    metadata.replace.assert_called_once()


def test_processes_rgb_png(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    output = tmp_path / "output.png"
    _pattern(320, 180).save(source)

    result = _processor().process(source, output, BASE_PROFILE)

    with Image.open(output) as processed:
        processed.load()
        assert processed.format == "PNG"
        assert processed.mode == "RGB"
        assert processed.size == (320, 180)
    assert result.output_format == "PNG"


def test_processes_rgba_png_and_preserves_transformed_alpha(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    output = tmp_path / "output.png"
    original = _pattern(301, 199, alpha=True)
    original.save(source)
    from core.image_filters import apply_micro_zoom

    expected_alpha = apply_micro_zoom(original, BASE_PROFILE.zoom_percent).getchannel("A")
    _processor().process(source, output, BASE_PROFILE)

    with Image.open(output) as processed:
        processed.load()
        assert processed.mode == "RGBA"
        assert processed.size == (301, 199)
        assert np.array_equal(
            np.asarray(processed.getchannel("A")),
            np.asarray(expected_alpha),
        )


@pytest.mark.parametrize("size", ((180, 320), (320, 180), (301, 199)))
def test_processor_zoom_preserves_portrait_landscape_and_odd_sizes(
    tmp_path: Path,
    size: tuple[int, int],
) -> None:
    source = tmp_path / f"input_{size[0]}_{size[1]}.png"
    output = tmp_path / f"output_{size[0]}_{size[1]}.png"
    _pattern(*size).save(source)

    _processor().process(source, output, BASE_PROFILE)

    with Image.open(output) as processed:
        assert processed.size == size


def test_jpeg_quality_affects_encoded_size(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    low = tmp_path / "low.jpg"
    high = tmp_path / "high.jpg"
    _pattern(320, 240).save(source)

    _processor().process(source, low, replace(BASE_PROFILE, jpeg_quality=30))
    _processor().process(source, high, replace(BASE_PROFILE, jpeg_quality=96))

    assert high.stat().st_size > low.stat().st_size


def test_jpeg_metadata_mapping(tmp_path: Path) -> None:
    source = tmp_path / "input.jpg"
    output = tmp_path / "output.jpg"
    _pattern(32, 24).save(source)
    metadata = Mock()

    _processor(metadata).process(source, output, BASE_PROFILE)

    metadata.replace.assert_called_once_with(
        output,
        {
            "EXIF:Make": "Apple",
            "EXIF:Model": "iPhone 14 Pro",
            "EXIF:DateTimeOriginal": "2026:08:09 05:59:11",
            "EXIF:CreateDate": "2026:08:09 05:59:11",
            "EXIF:ModifyDate": "2026:08:09 05:59:11",
        },
    )


def test_png_uses_supported_xmp_metadata_mapping(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    output = tmp_path / "output.png"
    _pattern(32, 24).save(source)
    metadata = Mock()

    _processor(metadata).process(source, output, BASE_PROFILE)

    tags = metadata.replace.call_args.args[1]
    assert tags["XMP-tiff:Make"] == "Apple"
    assert tags["XMP-tiff:Model"] == "iPhone 14 Pro"
    assert tags["XMP-exif:DateTimeOriginal"] == "2026:08:09 05:59:11"
    assert "EXIF:Make" not in tags


def test_get_image_info_reports_alpha(tmp_path: Path) -> None:
    source = tmp_path / "alpha.png"
    _pattern(17, 13, alpha=True).save(source)
    info = get_image_info(source)
    assert info.width == 17 and info.height == 13
    assert info.format == "PNG"
    assert info.mode == "RGBA"
    assert info.has_alpha is True


def test_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        _processor().process(
            tmp_path / "missing.jpg",
            tmp_path / "output.jpg",
            BASE_PROFILE,
        )


def test_rejects_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "input.jpg"
    output = tmp_path / "output.jpg"
    _pattern(16, 16).save(source)
    output.touch()
    with pytest.raises(FileExistsError, match="already exists"):
        _processor().process(source, output, BASE_PROFILE)


def test_rejects_same_input_and_output(tmp_path: Path) -> None:
    source = tmp_path / "input.jpg"
    _pattern(16, 16).save(source)
    with pytest.raises(ImageProcessingError, match="must be different"):
        _processor().process(source, source, BASE_PROFILE)


def test_rejects_corrupt_image(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.jpg"
    source.write_bytes(b"not a jpeg")
    with pytest.raises(ImageProcessingError, match="Image processing failed"):
        _processor().process(source, tmp_path / "output.jpg", BASE_PROFILE)
    with pytest.raises(ImageInspectionError, match="Cannot inspect"):
        get_image_info(source)


def test_rejects_unsupported_input_and_output(tmp_path: Path) -> None:
    unsupported = tmp_path / "input.webp"
    unsupported.touch()
    with pytest.raises(UnsupportedImageFormatError, match="unsupported"):
        _processor().process(unsupported, tmp_path / "output.jpg", BASE_PROFILE)

    source = tmp_path / "input.jpg"
    _pattern(16, 16).save(source)
    with pytest.raises(UnsupportedImageFormatError, match="unsupported"):
        _processor().process(source, tmp_path / "output.webp", BASE_PROFILE)
