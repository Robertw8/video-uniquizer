"""Tests for device registry, preset selection, and capability validation."""

import random
from dataclasses import replace
from datetime import datetime

import pytest

from core.params import ProfileGenerator
from devices.apple import STANDARD_FPS as APPLE_STANDARD_FPS
from devices.registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceRegistry,
    UnknownDeviceError,
)
from devices.samsung import STANDARD_FPS as SAMSUNG_STANDARD_FPS
from devices.validation import validate_image_profile, validate_video_profile

ALLOWED_STANDARD_FPS = {23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0}
FIXED_NOW = datetime(2026, 8, 18, 12, 0, 0)


def test_registry_lists_unique_supported_models() -> None:
    devices = DEFAULT_DEVICE_REGISTRY.list_devices()
    models = [device.model for device in devices]

    assert len(devices) == 10
    assert len(models) == len(set(models))
    assert models == [
        "iPhone 12",
        "iPhone 13",
        "iPhone 13 Pro",
        "iPhone 14",
        "iPhone 14 Pro",
        "iPhone 15",
        "iPhone 15 Pro",
        "Galaxy S22",
        "Galaxy S23",
        "Galaxy S24",
    ]


def test_registry_gets_known_device_and_explains_unknown_device() -> None:
    assert DEFAULT_DEVICE_REGISTRY.get_device("iPhone 14 Pro").make == "Apple"
    assert DEFAULT_DEVICE_REGISTRY.get_device("galaxy s23").make == "Samsung"

    with pytest.raises(UnknownDeviceError) as error:
        DEFAULT_DEVICE_REGISTRY.get_device("Nokia 3310")
    assert "Unknown device: Nokia 3310" in str(error.value)
    assert "Available devices:" in str(error.value)
    assert "Galaxy S23" in str(error.value)


def test_random_device_selection_is_seeded() -> None:
    first_rng = random.Random(42)
    second_rng = random.Random(42)

    first = [DEFAULT_DEVICE_REGISTRY.get_random_device(first_rng) for _ in range(8)]
    second = [DEFAULT_DEVICE_REGISTRY.get_random_device(second_rng) for _ in range(8)]

    assert first == second
    assert len({device.model for device in first}) > 1


def test_registry_rejects_duplicate_models() -> None:
    preset = DEFAULT_DEVICE_REGISTRY.get_device("iPhone 12")
    with pytest.raises(ValueError, match="unique"):
        DeviceRegistry((preset, preset))


def test_presets_only_declare_standard_fps() -> None:
    assert set(APPLE_STANDARD_FPS) == ALLOWED_STANDARD_FPS
    assert set(SAMSUNG_STANDARD_FPS) == ALLOWED_STANDARD_FPS
    for preset in DEFAULT_DEVICE_REGISTRY.list_devices():
        assert set(preset.allowed_fps) <= ALLOWED_STANDARD_FPS
        assert set(preset.preferred_fps) <= set(preset.allowed_fps)


def test_explicit_device_and_seed_are_reproducible() -> None:
    first = ProfileGenerator(
        random.Random(42),
        FIXED_NOW,
        "iPhone 14 Pro",
    ).generate_video_profile()
    second = ProfileGenerator(
        random.Random(42),
        FIXED_NOW,
        "iPhone 14 Pro",
    ).generate_video_profile()

    assert first == second
    assert first.device_model == "iPhone 14 Pro"


def test_automatic_device_and_seed_are_reproducible() -> None:
    first = ProfileGenerator(random.Random(123), FIXED_NOW).generate_image_profile()
    second = ProfileGenerator(random.Random(123), FIXED_NOW).generate_image_profile()

    assert first == second


def test_profile_validation_rejects_inconsistent_values() -> None:
    profile = ProfileGenerator(
        random.Random(7),
        FIXED_NOW,
        "Galaxy S23",
    ).generate_video_profile()

    with pytest.raises(ValueError, match="FPS"):
        validate_video_profile(replace(profile, fps=27.0))
    with pytest.raises(UnknownDeviceError):
        validate_video_profile(replace(profile, device_model="Unknown Phone"))


def test_generated_profiles_never_escape_device_capabilities() -> None:
    for seed in range(500):
        video = ProfileGenerator(random.Random(seed), FIXED_NOW).generate_video_profile()
        image = ProfileGenerator(random.Random(seed), FIXED_NOW).generate_image_profile()

        video_preset = validate_video_profile(video)
        image_preset = validate_image_profile(image)
        assert video.device_model == video_preset.model
        assert image.device_model == image_preset.model
