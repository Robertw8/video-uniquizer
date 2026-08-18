"""Generation of realistic profiles constrained by smartphone presets."""

import random
from datetime import datetime, timedelta

from devices.base import DevicePreset
from devices.registry import DEFAULT_DEVICE_REGISTRY, DeviceRegistry
from devices.validation import validate_image_profile, validate_video_profile
from models.profile import ImageProcessingProfile, VideoProcessingProfile

SmartphonePreset = DevicePreset
SMARTPHONE_PRESETS = DEFAULT_DEVICE_REGISTRY.list_devices()
MAX_CAPTURE_AGE_DAYS = 30


class ProfileGenerator:
    """Create coherent parameter sets from registered device capabilities.

    A random number generator and clock can be supplied by callers, which makes
    automatic and explicitly selected device profiles fully reproducible.
    """

    def __init__(
        self,
        rng: random.Random | None = None,
        now: datetime | None = None,
        device_model: str | None = None,
        registry: DeviceRegistry = DEFAULT_DEVICE_REGISTRY,
    ) -> None:
        self._rng = rng or random.Random()
        self._registry = registry
        self._selected_device = (
            registry.get_device(device_model) if device_model is not None else None
        )
        if now is None:
            local_now = datetime.now().astimezone().replace(tzinfo=None)
            self._now = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            self._now = now

    def generate_video_profile(self) -> VideoProcessingProfile:
        """Generate a subtle video profile inside one device preset."""
        preset = self._device()
        profile = VideoProcessingProfile(
            device_model=preset.model,
            creation_date=self._creation_date(),
            fps=self._rng.choice(preset.preferred_fps),
            speed_multiplier=self._triangular(preset.speed_range, 1.0, 3),
            zoom_percent=self._preferred_integer(preset.zoom_range, 1),
            brightness=self._triangular(preset.brightness_range, 0.0, 3),
            contrast=self._triangular(preset.contrast_range, 1.0, 2),
            saturation=self._triangular(preset.saturation_range, 1.0, 2),
            sharpness=self._triangular(
                preset.sharpness_range,
                sum(preset.sharpness_range) / 2,
                2,
            ),
            noise_level=self._rng.choice(preset.noise_levels),
            crf=self._preferred_integer(preset.crf_range, 24),
        )
        validate_video_profile(profile, self._registry)
        return profile

    def generate_image_profile(self) -> ImageProcessingProfile:
        """Generate a subtle image profile inside one device preset."""
        preset = self._device()
        profile = ImageProcessingProfile(
            device_model=preset.model,
            creation_date=self._creation_date(),
            jpeg_quality=self._preferred_integer(preset.jpeg_quality_range, 94),
            zoom_percent=self._preferred_integer(preset.image_zoom_range, 1),
            brightness=self._triangular(
                preset.image_brightness_range,
                1.0,
                2,
            ),
            contrast=self._triangular(preset.image_contrast_range, 1.0, 2),
            saturation=self._triangular(preset.image_saturation_range, 1.0, 2),
            sharpness=self._triangular(
                preset.image_sharpness_range,
                sum(preset.image_sharpness_range) / 2,
                2,
            ),
            noise_level=self._rng.choice(preset.image_noise_levels),
        )
        validate_image_profile(profile, self._registry)
        return profile

    def _device(self) -> DevicePreset:
        return self._selected_device or self._registry.get_random_device(self._rng)

    def _creation_date(self) -> datetime:
        """Choose a capture time during one of the previous 30 local days."""
        reference_date = self._now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        days_back = self._rng.randint(1, MAX_CAPTURE_AGE_DAYS)
        seconds_into_day = self._rng.randint(0, 24 * 60 * 60 - 1)
        return (
            reference_date
            - timedelta(days=days_back)
            + timedelta(seconds=seconds_into_day)
        )

    def _triangular(
        self,
        limits: tuple[float, float],
        mode: float,
        digits: int,
    ) -> float:
        bounded_mode = max(limits[0], min(limits[1], mode))
        return round(self._rng.triangular(*limits, bounded_mode), digits)

    def _preferred_integer(
        self,
        limits: tuple[int, int],
        preferred: int,
    ) -> int:
        values = tuple(range(limits[0], limits[1] + 1))
        bounded_preferred = max(limits[0], min(limits[1], preferred))
        weights = tuple(4 if value == bounded_preferred else 1 for value in values)
        return self._rng.choices(values, weights=weights, k=1)[0]


def generate_video_profile(
    rng: random.Random | None = None,
    now: datetime | None = None,
    device_model: str | None = None,
) -> VideoProcessingProfile:
    """Convenience function for generating a video profile."""
    return ProfileGenerator(
        rng=rng,
        now=now,
        device_model=device_model,
    ).generate_video_profile()


def generate_image_profile(
    rng: random.Random | None = None,
    now: datetime | None = None,
    device_model: str | None = None,
) -> ImageProcessingProfile:
    """Convenience function for generating an image profile."""
    return ProfileGenerator(
        rng=rng,
        now=now,
        device_model=device_model,
    ).generate_image_profile()
