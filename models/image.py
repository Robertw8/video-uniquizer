"""Domain models returned by image inspection and processing."""

from dataclasses import dataclass
from pathlib import Path

from .profile import ImageProcessingProfile


@dataclass(frozen=True, slots=True)
class ImageInfo:
    """Normalized technical information about an image."""

    width: int
    height: int
    format: str
    mode: str
    has_alpha: bool


@dataclass(frozen=True, slots=True)
class ImageProcessingResult:
    """Result returned after a successful image processing run."""

    input_file: Path
    output_file: Path
    profile: ImageProcessingProfile
    processing_time: float
    width: int
    height: int
    output_format: str
