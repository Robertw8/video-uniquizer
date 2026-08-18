"""Preset-aware validation for generated processing profiles."""

from models.profile import ImageProcessingProfile, VideoProcessingProfile

from .base import DevicePreset
from .registry import DEFAULT_DEVICE_REGISTRY, DeviceRegistry


def _in_range(value: float, limits: tuple[float, float]) -> bool:
    return limits[0] <= value <= limits[1]


def _validate_value(name: str, value: float, limits: tuple[float, float]) -> None:
    if not _in_range(value, limits):
        raise ValueError(
            f"{name}={value} is outside device capability range "
            f"[{limits[0]}, {limits[1]}]."
        )


def validate_video_profile(
    profile: VideoProcessingProfile,
    registry: DeviceRegistry = DEFAULT_DEVICE_REGISTRY,
) -> DevicePreset:
    """Validate that every video value belongs to its registered preset."""
    preset = registry.get_device(profile.device_model)
    if profile.fps not in preset.allowed_fps:
        allowed = ", ".join(f"{value:g}" for value in preset.allowed_fps)
        raise ValueError(
            f"FPS={profile.fps:g} is not supported by {preset.model}. "
            f"Allowed FPS: {allowed}."
        )
    _validate_value("speed_multiplier", profile.speed_multiplier, preset.speed_range)
    _validate_value("zoom_percent", profile.zoom_percent, preset.zoom_range)
    _validate_value("brightness", profile.brightness, preset.brightness_range)
    _validate_value("contrast", profile.contrast, preset.contrast_range)
    _validate_value("saturation", profile.saturation, preset.saturation_range)
    _validate_value("sharpness", profile.sharpness, preset.sharpness_range)
    if profile.noise_level not in preset.noise_levels:
        raise ValueError(
            f"noise_level={profile.noise_level} is not supported by {preset.model}."
        )
    _validate_value("crf", profile.crf, preset.crf_range)
    return preset


def validate_image_profile(
    profile: ImageProcessingProfile,
    registry: DeviceRegistry = DEFAULT_DEVICE_REGISTRY,
) -> DevicePreset:
    """Validate that every image value belongs to its registered preset."""
    preset = registry.get_device(profile.device_model)
    _validate_value("jpeg_quality", profile.jpeg_quality, preset.jpeg_quality_range)
    _validate_value("zoom_percent", profile.zoom_percent, preset.image_zoom_range)
    _validate_value(
        "brightness", profile.brightness, preset.image_brightness_range
    )
    _validate_value("contrast", profile.contrast, preset.image_contrast_range)
    _validate_value("saturation", profile.saturation, preset.image_saturation_range)
    _validate_value("sharpness", profile.sharpness, preset.image_sharpness_range)
    if profile.noise_level not in preset.image_noise_levels:
        raise ValueError(
            f"noise_level={profile.noise_level} is not supported by {preset.model}."
        )
    return preset
