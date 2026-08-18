"""Domain models returned by video inspection and processing."""

from dataclasses import dataclass
from pathlib import Path

from .profile import VideoProcessingProfile


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """Normalized technical information about a video stream."""

    width: int
    height: int
    fps: float
    duration_seconds: float
    codec: str
    bitrate: int | None
    audio_streams: int


@dataclass(frozen=True, slots=True)
class VideoProcessingResult:
    """Result returned after a successful video processing run."""

    input_file: Path
    output_file: Path
    profile: VideoProcessingProfile
    processing_time: float
    ffmpeg_command: tuple[str, ...]
