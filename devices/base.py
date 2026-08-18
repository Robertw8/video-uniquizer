"""Immutable domain model for a smartphone processing preset."""

from dataclasses import dataclass

FloatRange = tuple[float, float]
IntRange = tuple[int, int]


@dataclass(frozen=True, slots=True)
class DevicePreset:
    """Capabilities and subtle processing limits for one smartphone model."""

    manufacturer: str
    model: str
    platform: str
    family: str

    allowed_fps: tuple[float, ...]
    preferred_fps: tuple[float, ...]
    video_codec: str
    pixel_format: str
    crf_range: IntRange
    speed_range: FloatRange
    zoom_range: IntRange
    brightness_range: FloatRange
    contrast_range: FloatRange
    saturation_range: FloatRange
    sharpness_range: FloatRange
    noise_levels: tuple[int, ...]

    jpeg_quality_range: IntRange
    image_zoom_range: IntRange
    image_brightness_range: FloatRange
    image_contrast_range: FloatRange
    image_saturation_range: FloatRange
    image_sharpness_range: FloatRange
    image_noise_levels: tuple[int, ...]

    make: str
    metadata_family: str
