"""Central registry for all supported smartphone presets."""

import random
from collections.abc import Iterable

from .apple import APPLE_PRESETS
from .base import DevicePreset
from .samsung import SAMSUNG_PRESETS

REGISTERED_DEVICES = APPLE_PRESETS + SAMSUNG_PRESETS


class UnknownDeviceError(ValueError):
    """Raised when a requested smartphone model is not registered."""


class DeviceRegistry:
    """Resolve and select immutable device presets without processing concerns."""

    def __init__(self, devices: Iterable[DevicePreset] = REGISTERED_DEVICES) -> None:
        self._devices = tuple(devices)
        self._by_name = {device.model.casefold(): device for device in self._devices}
        if len(self._by_name) != len(self._devices):
            raise ValueError("Device models in the registry must be unique.")

    def get_device(self, model: str) -> DevicePreset:
        """Return a preset by model name, using a case-insensitive lookup."""
        try:
            return self._by_name[model.strip().casefold()]
        except KeyError as exc:
            available = "\n".join(f"- {item.model}" for item in self._devices)
            raise UnknownDeviceError(
                f"Unknown device: {model}\nAvailable devices:\n{available}"
            ) from exc

    def list_devices(self) -> tuple[DevicePreset, ...]:
        """Return all registered presets in stable display order."""
        return self._devices

    def get_random_device(self, rng: random.Random) -> DevicePreset:
        """Select a preset through the caller-provided random generator."""
        if not self._devices:
            raise LookupError("No device presets are registered.")
        return rng.choice(self._devices)


DEFAULT_DEVICE_REGISTRY = DeviceRegistry()


def get_device(model: str) -> DevicePreset:
    """Resolve a preset from the default registry."""
    return DEFAULT_DEVICE_REGISTRY.get_device(model)


def list_devices() -> tuple[DevicePreset, ...]:
    """List presets from the default registry."""
    return DEFAULT_DEVICE_REGISTRY.list_devices()


def get_random_device(rng: random.Random) -> DevicePreset:
    """Select a preset from the default registry."""
    return DEFAULT_DEVICE_REGISTRY.get_random_device(rng)
