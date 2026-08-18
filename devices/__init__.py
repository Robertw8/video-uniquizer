"""Smartphone capability presets used by profile generation."""

from .base import DevicePreset
from .registry import (
    DEFAULT_DEVICE_REGISTRY,
    DeviceRegistry,
    UnknownDeviceError,
    get_device,
    get_random_device,
    list_devices,
)
from .validation import validate_image_profile, validate_video_profile

__all__ = [
    "DEFAULT_DEVICE_REGISTRY",
    "DevicePreset",
    "DeviceRegistry",
    "UnknownDeviceError",
    "get_device",
    "get_random_device",
    "list_devices",
    "validate_image_profile",
    "validate_video_profile",
]
