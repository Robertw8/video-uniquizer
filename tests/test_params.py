"""Tests for realistic and reproducible profile generation."""

import random
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from core.params import MAX_CAPTURE_AGE_DAYS, SMARTPHONE_PRESETS, ProfileGenerator


def test_video_profile_is_reproducible() -> None:
    now = datetime(2026, 8, 17, 12, 0, 0)
    first = ProfileGenerator(random.Random(42), now).generate_video_profile()
    second = ProfileGenerator(random.Random(42), now).generate_video_profile()

    assert first == second


@patch("core.params.datetime")
def test_default_clock_is_stable_during_the_same_day(mock_datetime: Mock) -> None:
    mock_datetime.now.side_effect = (
        datetime(2026, 8, 18, 0, 0, 1).astimezone(),
        datetime(2026, 8, 18, 23, 59, 59).astimezone(),
    )

    morning = ProfileGenerator(random.Random(42)).generate_video_profile()
    evening = ProfileGenerator(random.Random(42)).generate_video_profile()

    assert morning == evening


def test_video_profile_uses_realistic_ranges() -> None:
    now = datetime(2026, 8, 17, 12, 0, 0)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    known_models = {preset.model for preset in SMARTPHONE_PRESETS}

    for seed in range(100):
        profile = ProfileGenerator(random.Random(seed), now).generate_video_profile()
        assert profile.device_model in known_models
        assert (
            start_of_today - timedelta(days=MAX_CAPTURE_AGE_DAYS)
            <= profile.creation_date
            < start_of_today
        )
        assert 0.985 <= profile.speed_multiplier <= 1.025
        assert profile.zoom_percent in {0, 1, 2}
        assert -0.025 <= profile.brightness <= 0.025
        assert 0.97 <= profile.contrast <= 1.04
        assert 0.96 <= profile.saturation <= 1.04
        assert 0.25 <= profile.sharpness <= 0.55
        assert profile.noise_level in {1, 2}
        assert profile.crf in {22, 23, 24, 25}


def test_video_creation_dates_stay_within_previous_30_days() -> None:
    start_of_today = datetime(2026, 8, 18)
    dates = {
        ProfileGenerator(random.Random(seed), start_of_today)
        .generate_video_profile()
        .creation_date
        for seed in range(500)
    }

    assert len(dates) > MAX_CAPTURE_AGE_DAYS
    for creation_date in dates:
        assert start_of_today - timedelta(days=MAX_CAPTURE_AGE_DAYS) <= creation_date
        assert creation_date < start_of_today
        assert creation_date.date() != start_of_today.date()


def test_image_creation_dates_stay_within_previous_30_days() -> None:
    start_of_today = datetime(2026, 8, 18)
    dates = {
        ProfileGenerator(random.Random(seed), start_of_today)
        .generate_image_profile()
        .creation_date
        for seed in range(500)
    }

    assert len(dates) > MAX_CAPTURE_AGE_DAYS
    for creation_date in dates:
        assert start_of_today - timedelta(days=MAX_CAPTURE_AGE_DAYS) <= creation_date
        assert creation_date < start_of_today
        assert creation_date.date() != start_of_today.date()


def test_creation_date_is_seeded_for_video_and_image() -> None:
    start_of_today = datetime(2026, 8, 18)

    first_video = ProfileGenerator(
        random.Random(42), start_of_today
    ).generate_video_profile()
    second_video = ProfileGenerator(
        random.Random(42), start_of_today
    ).generate_video_profile()
    first_image = ProfileGenerator(
        random.Random(42), start_of_today
    ).generate_image_profile()
    second_image = ProfileGenerator(
        random.Random(42), start_of_today
    ).generate_image_profile()

    assert first_video.creation_date == second_video.creation_date
    assert first_image.creation_date == second_image.creation_date


def test_image_profile_uses_device_specific_quality() -> None:
    now = datetime(2026, 8, 17, 12, 0, 0)
    ranges = {preset.model: preset.jpeg_quality_range for preset in SMARTPHONE_PRESETS}

    for seed in range(50):
        profile = ProfileGenerator(random.Random(seed), now).generate_image_profile()
        minimum, maximum = ranges[profile.device_model]
        assert minimum <= profile.jpeg_quality <= maximum
        assert profile.zoom_percent in {0, 1, 2}
        assert 0.97 <= profile.brightness <= 1.03
        assert 0.97 <= profile.contrast <= 1.04
        assert 0.96 <= profile.saturation <= 1.04
