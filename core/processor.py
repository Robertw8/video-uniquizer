"""Application-level orchestration for media analysis and planning."""

import random
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core.image import ImageProcessor, inspect_image
from core.params import ProfileGenerator
from core.video import VideoProcessingResult, VideoProcessor, inspect_video
from models.image import ImageProcessingResult
from models.profile import (
    ImageProcessingProfile,
    ProcessingProfile,
    VideoProcessingProfile,
)

VIDEO_EXTENSIONS = frozenset({".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"})
IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png"})


class MediaKind(str, Enum):
    """Supported high-level media categories."""

    VIDEO = "video"
    IMAGE = "image"


class UnsupportedMediaError(ValueError):
    """Raised when the engine cannot map a file to a supported media type."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Normalized information collected from a media file."""

    path: Path
    kind: MediaKind
    size_bytes: int
    properties: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProcessingPlan:
    """Immutable pairing of source information and generated parameters."""

    media: MediaInfo
    profile: ProcessingProfile


class MediaProcessor:
    """Coordinate file inspection and profile generation.

    This class is intentionally interface-agnostic: CLI, API, bot, or a job
    worker can all call the same methods.
    """

    def __init__(
        self,
        profile_generator: ProfileGenerator | None = None,
        video_processor: VideoProcessor | None = None,
        image_processor: ImageProcessor | None = None,
    ) -> None:
        self._profile_generator = profile_generator or ProfileGenerator()
        self._video_processor = video_processor or VideoProcessor()
        self._image_processor = image_processor or ImageProcessor()

    @classmethod
    def with_seed(
        cls,
        seed: int,
        device_model: str | None = None,
    ) -> "MediaProcessor":
        """Create a processor whose generated plans are reproducible."""
        return cls(
            ProfileGenerator(
                rng=random.Random(seed),
                device_model=device_model,
            )
        )

    @classmethod
    def for_device(
        cls,
        device_model: str,
        seed: int | None = None,
    ) -> "MediaProcessor":
        """Create a processor constrained to one explicit device preset."""
        rng = random.Random(seed) if seed is not None else None
        return cls(ProfileGenerator(rng=rng, device_model=device_model))

    def detect_media_kind(self, path: str | Path) -> MediaKind:
        """Determine media category from a supported file extension."""
        suffix = Path(path).suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            return MediaKind.VIDEO
        if suffix in IMAGE_EXTENSIONS:
            return MediaKind.IMAGE
        supported = ", ".join(sorted(VIDEO_EXTENSIONS | IMAGE_EXTENSIONS))
        raise UnsupportedMediaError(
            f"Unsupported media extension '{suffix or '<none>'}'. Supported: {supported}"
        )

    def analyze(self, path: str | Path) -> MediaInfo:
        """Validate and inspect an input media file."""
        media_path = Path(path).expanduser().resolve()
        if not media_path.is_file():
            raise FileNotFoundError(f"Input file does not exist: {media_path}")

        kind = self.detect_media_kind(media_path)
        properties = (
            inspect_video(media_path)
            if kind is MediaKind.VIDEO
            else inspect_image(media_path)
        )
        return MediaInfo(
            path=media_path,
            kind=kind,
            size_bytes=media_path.stat().st_size,
            properties=properties,
        )

    def build_plan(self, path: str | Path) -> ProcessingPlan:
        """Inspect a file and generate suitable future processing parameters."""
        media = self.analyze(path)
        profile: ProcessingProfile
        if media.kind is MediaKind.VIDEO:
            profile = self._profile_generator.generate_video_profile()
        else:
            profile = self._profile_generator.generate_image_profile()
        return ProcessingPlan(media=media, profile=profile)

    def process(
        self,
        source: ProcessingPlan | str | Path,
        output_path: str | Path,
    ) -> VideoProcessingResult | ImageProcessingResult:
        """Apply a supported processing plan to a destination file."""
        plan = source if isinstance(source, ProcessingPlan) else self.build_plan(source)
        if (
            plan.media.kind is MediaKind.VIDEO
            and isinstance(plan.profile, VideoProcessingProfile)
        ):
            return self._video_processor.process(
                plan.media.path,
                output_path,
                plan.profile,
                has_audio=bool(plan.media.properties.get("audio_streams", 0)),
            )
        if (
            plan.media.kind is MediaKind.IMAGE
            and isinstance(plan.profile, ImageProcessingProfile)
        ):
            return self._image_processor.process(
                plan.media.path,
                output_path,
                plan.profile,
            )
        raise TypeError("Processing plan media type and profile type do not match.")
