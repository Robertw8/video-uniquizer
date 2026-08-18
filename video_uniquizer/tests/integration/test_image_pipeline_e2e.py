"""End-to-end image tests using real Pillow files and ExifTool metadata."""

import subprocess
import sys

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageChops

from core.image import ImageProcessor
from core.image_filters import apply_micro_zoom
from core.processor import MediaProcessor
from engines.exiftool import read_metadata
from models.profile import ImageProcessingProfile

pytestmark = pytest.mark.integration

PROFILE = ImageProcessingProfile(
    device_model="iPhone 14 Pro",
    creation_date=datetime(2026, 8, 9, 5, 59, 11),
    brightness=1.02,
    contrast=1.03,
    saturation=0.98,
    sharpness=0.36,
    noise_level=2,
    jpeg_quality=93,
    zoom_percent=2,
)


def _metadata_values(metadata: dict[str, Any], tag_name: str) -> list[Any]:
    return [
        value
        for key, value in metadata.items()
        if key.rsplit(":", maxsplit=1)[-1] == tag_name
    ]


@pytest.mark.parametrize(
    ("fixture_name", "suffix", "expected_format", "expected_mode"),
    (
        ("portrait", ".jpg", "JPEG", "RGB"),
        ("landscape", ".jpeg", "JPEG", "RGB"),
        ("rgb_png", ".png", "PNG", "RGB"),
        ("rgba_png", ".png", "PNG", "RGBA"),
        ("odd", ".jpg", "JPEG", "RGB"),
    ),
)
def test_real_image_pipeline_preserves_contract(
    generated_images: dict[str, Path],
    tmp_path: Path,
    fixture_name: str,
    suffix: str,
    expected_format: str,
    expected_mode: str,
) -> None:
    source = generated_images[fixture_name]
    output = tmp_path / f"processed_{fixture_name}{suffix}"
    with Image.open(source) as input_image:
        input_image.load()
        input_size = input_image.size
        input_rgb = input_image.convert("RGB")

    result = ImageProcessor().process(source, output, PROFILE)

    assert result.output_file == output
    assert output.is_file() and output.stat().st_size > 0
    with Image.open(output) as verification:
        verification.verify()
    with Image.open(output) as processed:
        processed.load()
        assert processed.format == expected_format
        assert processed.mode == expected_mode
        assert processed.size == input_size
        assert processed.width / processed.height == pytest.approx(
            input_size[0] / input_size[1]
        )
        assert ImageChops.difference(
            input_rgb,
            processed.convert("RGB"),
        ).getbbox() is not None

    metadata = read_metadata(output)
    assert _metadata_values(metadata, "Make") == ["Apple"]
    assert _metadata_values(metadata, "Model") == [PROFILE.device_model]
    assert _metadata_values(metadata, "DateTimeOriginal")


def test_real_rgba_alpha_is_only_geometrically_transformed(
    generated_images: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = generated_images["rgba_png"]
    output = tmp_path / "alpha_result.png"
    with Image.open(source) as original:
        original.load()
        expected_alpha = apply_micro_zoom(
            original.convert("RGBA"),
            PROFILE.zoom_percent,
        ).getchannel("A")

    ImageProcessor().process(source, output, PROFILE)

    with Image.open(output) as processed:
        processed.load()
        assert processed.mode == "RGBA"
        assert np.array_equal(
            np.asarray(processed.getchannel("A")),
            np.asarray(expected_alpha),
        )


def test_real_jpeg_metadata_is_replaced(
    generated_images: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = generated_images["legacy"]
    output = tmp_path / "metadata_result.jpg"
    before = read_metadata(source)

    ImageProcessor().process(source, output, PROFILE)

    after = read_metadata(output)
    assert _metadata_values(before, "Artist") == ["Legacy Artist"]
    assert _metadata_values(before, "UserComment") == ["Legacy Comment"]
    assert _metadata_values(before, "Make") == ["Legacy Make"]
    assert _metadata_values(before, "Model") == ["Legacy Model"]
    assert not _metadata_values(after, "Artist")
    assert not _metadata_values(after, "UserComment")
    assert _metadata_values(after, "Make") == ["Apple"]
    assert _metadata_values(after, "Model") == [PROFILE.device_model]
    for tag in ("DateTimeOriginal", "CreateDate"):
        values = _metadata_values(after, tag)
        assert len(values) == 1
        assert str(values[0]).startswith("2026:08:09 05:59:11")


def test_real_seeded_image_profiles_are_reproducible(
    generated_images: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = generated_images["landscape"]
    first = MediaProcessor.with_seed(42).build_plan(source).profile
    repeated = MediaProcessor.with_seed(42).build_plan(source).profile
    assert first == repeated

    profiles: list[ImageProcessingProfile] = []
    for seed in (1, 42, 123):
        processor = MediaProcessor.with_seed(seed)
        plan = processor.build_plan(source)
        assert isinstance(plan.profile, ImageProcessingProfile)
        profiles.append(plan.profile)
        result = processor.process(plan, tmp_path / f"seed_{seed}.jpg")
        with Image.open(result.output_file) as processed:
            processed.verify()
    assert len(set(profiles)) == 3


def test_cli_explicit_samsung_device_processes_jpeg_and_writes_metadata(
    generated_images: dict[str, Path],
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "explicit_samsung.jpg"

    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "cli.py"),
            str(generated_images["landscape"]),
            "--output",
            str(output),
            "--device",
            "Galaxy S23",
            "--seed",
            "42",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "📱 Device: Galaxy S23" in completed.stdout
    with Image.open(output) as processed:
        processed.verify()
    metadata = read_metadata(output)
    assert _metadata_values(metadata, "Make") == ["Samsung"]
    assert _metadata_values(metadata, "Model") == ["Galaxy S23"]
