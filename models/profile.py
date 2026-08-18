"""Typed processing profiles used by the core engine."""

from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class BaseProcessingProfile:
    """Parameters shared by image and video processing profiles."""

    device_model: str
    creation_date: datetime
    brightness: float
    contrast: float
    saturation: float
    sharpness: float
    noise_level: int


@dataclass(frozen=True, slots=True)
class VideoProcessingProfile(BaseProcessingProfile):
    """A complete set of parameters for a future video transform."""

    fps: float
    speed_multiplier: float
    zoom_percent: int
    crf: int


@dataclass(frozen=True, slots=True)
class ImageProcessingProfile(BaseProcessingProfile):
    """A complete set of parameters for a future image transform."""

    jpeg_quality: int
    zoom_percent: int = 0


ProcessingProfile: TypeAlias = VideoProcessingProfile | ImageProcessingProfile

VideoProfile = VideoProcessingProfile
ImageProfile = ImageProcessingProfile
