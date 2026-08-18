"""Unit tests for pure Pillow image transformations."""

from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest
from PIL import Image, ImageChops, ImageStat

from core.image_filters import (
    add_noise,
    apply_color_adjustments,
    apply_micro_zoom,
)
from models.profile import ImageProcessingProfile

BASE_PROFILE = ImageProcessingProfile(
    device_model="iPhone 14 Pro",
    creation_date=datetime(2026, 8, 9, 5, 59, 11),
    brightness=1.0,
    contrast=1.0,
    saturation=1.0,
    sharpness=0.0,
    noise_level=0,
    jpeg_quality=92,
    zoom_percent=0,
)


def _pattern(width: int = 33, height: int = 25) -> Image.Image:
    y, x = np.indices((height, width))
    values = np.stack((x * 7, y * 9, (x + y) * 5), axis=2)
    return Image.fromarray(np.mod(values, 256).astype(np.uint8))


@pytest.mark.parametrize("size", ((180, 320), (320, 180), (301, 199)))
def test_micro_zoom_preserves_exact_size_and_aspect_ratio(
    size: tuple[int, int],
) -> None:
    source = _pattern(*size)

    output = apply_micro_zoom(source, 2)

    assert output.size == size
    assert output.width / output.height == pytest.approx(size[0] / size[1])


def test_brightness_uses_pillow_multiplier_semantics() -> None:
    source = _pattern()
    output = apply_color_adjustments(
        source,
        replace(BASE_PROFILE, brightness=1.2),
    )
    assert ImageStat.Stat(output).mean[0] > ImageStat.Stat(source).mean[0]


def test_contrast_changes_pixel_distribution() -> None:
    source = _pattern()
    output = apply_color_adjustments(
        source,
        replace(BASE_PROFILE, contrast=1.3),
    )
    assert ImageStat.Stat(output).stddev[0] > ImageStat.Stat(source).stddev[0]


def test_saturation_changes_color_values() -> None:
    source = _pattern()
    output = apply_color_adjustments(
        source,
        replace(BASE_PROFILE, saturation=0.7),
    )
    assert ImageChops.difference(source, output).getbbox() is not None


def test_sharpness_amount_is_converted_to_pillow_factor() -> None:
    source = _pattern()
    output = apply_color_adjustments(
        source,
        replace(BASE_PROFILE, sharpness=0.5),
    )
    assert ImageChops.difference(source, output).getbbox() is not None


def test_noise_zero_is_pixel_identical() -> None:
    source = _pattern()
    output = add_noise(source, 0, np.random.default_rng(1))
    assert ImageChops.difference(source, output).getbbox() is None


def test_noise_changes_rgb_and_clamps_values() -> None:
    values = np.array([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8)
    source = Image.fromarray(values)
    output = add_noise(source, 100, np.random.default_rng(1))
    output_values = np.asarray(output)

    assert not np.array_equal(values, output_values)
    assert int(output_values.min()) >= 0
    assert int(output_values.max()) <= 255


def test_color_and_noise_preserve_alpha_after_zoom() -> None:
    rgb = np.asarray(_pattern(31, 19))
    alpha = np.arange(31 * 19, dtype=np.uint16).reshape(19, 31) % 256
    rgba = np.dstack((rgb, alpha.astype(np.uint8)))
    source = Image.fromarray(rgba)
    profile = replace(
        BASE_PROFILE,
        zoom_percent=2,
        brightness=1.1,
        contrast=1.1,
        saturation=0.9,
        sharpness=0.4,
        noise_level=2,
    )
    expected_alpha = apply_micro_zoom(source, 2).getchannel("A")
    adjusted = apply_color_adjustments(apply_micro_zoom(source, 2), profile)
    output = add_noise(adjusted, 2, np.random.default_rng(5))

    assert ImageChops.difference(output.getchannel("A"), expected_alpha).getbbox() is None
