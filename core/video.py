"""Video inspection and FFmpeg-based processing."""

import time
from collections.abc import Callable, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from core.metadata import MetadataService
from core.video_filters import build_filter_complex
from devices.registry import get_device
from engines.exiftool import ExifToolError
from engines.ffmpeg import MediaToolError, probe_file, run_ffmpeg
from models.profile import VideoProcessingProfile
from models.video import VideoInfo, VideoProcessingResult

SUPPORTED_VIDEO_CONTAINERS = frozenset({".mp4", ".mov"})
VIDEO_ENCODER = "libx264"


class VideoInspectionError(RuntimeError):
    """Raised when ffprobe output does not describe a video stream."""


class VideoProcessingError(RuntimeError):
    """Raised when a video cannot be processed."""


class UnsupportedVideoFormatError(VideoProcessingError):
    """Raised when an input or output container is unsupported."""


def _decimal_frame_rate(raw_value: object) -> float | None:
    if not isinstance(raw_value, str) or raw_value in {"0/0", "N/A", ""}:
        return None
    try:
        return round(float(Fraction(raw_value)), 3)
    except (ValueError, ZeroDivisionError):
        return None


def _optional_float(raw_value: object) -> float | None:
    try:
        return round(float(str(raw_value)), 3)
    except (TypeError, ValueError):
        return None


def _optional_int(raw_value: object) -> int | None:
    try:
        return int(str(raw_value))
    except (TypeError, ValueError):
        return None


def get_video_info(path: str | Path) -> VideoInfo:
    """Read required video properties through the existing ffprobe wrapper."""
    video_path = Path(path)
    probe = probe_file(video_path)
    streams = probe.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise VideoInspectionError(f"No video stream found in '{video_path}'.")

    format_info = probe.get("format", {})
    width = _optional_int(video_stream.get("width"))
    height = _optional_int(video_stream.get("height"))
    fps = _decimal_frame_rate(
        video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
    )
    duration = _optional_float(format_info.get("duration"))
    if duration is None:
        duration = _optional_float(video_stream.get("duration"))

    missing = [
        name
        for name, value in (
            ("width", width),
            ("height", height),
            ("fps", fps),
            ("duration", duration),
        )
        if value is None
    ]
    if missing:
        joined = ", ".join(missing)
        raise VideoInspectionError(
            f"ffprobe did not return required fields for '{video_path}': {joined}."
        )
    assert width is not None
    assert height is not None
    assert fps is not None
    assert duration is not None

    bitrate = _optional_int(
        video_stream.get("bit_rate") or format_info.get("bit_rate")
    )
    return VideoInfo(
        width=width,
        height=height,
        fps=fps,
        duration_seconds=duration,
        codec=str(video_stream.get("codec_name") or "unknown"),
        bitrate=bitrate,
        audio_streams=sum(
            1 for stream in streams if stream.get("codec_type") == "audio"
        ),
    )


def inspect_video(path: str | Path) -> dict[str, Any]:
    """Extract normalized video properties from ffprobe output."""
    info = get_video_info(path)
    return {
        "codec": info.codec,
        "width": info.width,
        "height": info.height,
        "duration_seconds": info.duration_seconds,
        "fps": info.fps,
        "bitrate": info.bitrate,
        "audio_streams": info.audio_streams,
    }


FfmpegRunner = Callable[[Sequence[str]], object]
Clock = Callable[[], float]


class VideoProcessor:
    """Process MP4/MOV videos using FFmpeg and ExifTool adapters."""

    def __init__(
        self,
        ffmpeg_runner: FfmpegRunner = run_ffmpeg,
        metadata_service: MetadataService | None = None,
        clock: Clock = time.perf_counter,
    ) -> None:
        self._run_ffmpeg = ffmpeg_runner
        self._metadata_service = (
            metadata_service if metadata_service is not None else MetadataService()
        )
        self._clock = clock

    def get_info(self, path: str | Path) -> VideoInfo:
        """Return normalized video details using ffprobe."""
        return get_video_info(path)

    def build_ffmpeg_command(
        self,
        input_path: str | Path,
        output_path: str | Path,
        profile: VideoProcessingProfile,
        *,
        has_audio: bool,
    ) -> tuple[str, ...]:
        """Build a complete H.264 FFmpeg command without executing it."""
        source = Path(input_path)
        destination = Path(output_path)
        self._validate_container(source, "Input")
        self._validate_container(destination, "Output")

        command = [
            "ffmpeg",
            "-hide_banner",
            "-n",
            "-i",
            str(source),
            "-filter_complex",
            build_filter_complex(profile),
            "-map",
            "[video]",
        ]
        if has_audio:
            command.extend(
                (
                    "-map",
                    "0:a:0",
                    "-filter:a",
                    f"atempo={profile.speed_multiplier:.3f}",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                )
            )

        command.extend(
            (
                "-c:v",
                VIDEO_ENCODER,
                "-preset",
                "medium",
                "-crf",
                str(profile.crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-map_metadata",
                "-1",
                str(destination),
            )
        )
        return tuple(command)

    def process(
        self,
        input_path: str | Path,
        output_path: str | Path,
        profile: VideoProcessingProfile,
        *,
        has_audio: bool | None = None,
    ) -> VideoProcessingResult:
        """Execute FFmpeg, update metadata, and return processing details."""
        source = Path(input_path).expanduser().resolve()
        destination = Path(output_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Input video does not exist: {source}")
        if source == destination:
            raise VideoProcessingError("Input and output paths must be different.")
        if destination.exists():
            raise FileExistsError(f"Output file already exists: {destination}")
        if not destination.parent.is_dir():
            raise FileNotFoundError(
                f"Output directory does not exist: {destination.parent}"
            )

        audio_available = (
            self.get_info(source).audio_streams > 0
            if has_audio is None
            else has_audio
        )
        command = self.build_ffmpeg_command(
            source,
            destination,
            profile,
            has_audio=audio_available,
        )

        started_at = self._clock()
        try:
            self._run_ffmpeg(command)
            preset = get_device(profile.device_model)
            self._metadata_service.replace(
                destination,
                {
                    "UserData:Make": preset.make,
                    "UserData:Model": preset.model,
                    "Keys:CreationDate": profile.creation_date.strftime(
                        "%Y:%m:%d %H:%M:%S"
                    ),
                },
            )
        except (MediaToolError, ExifToolError, OSError) as exc:
            raise VideoProcessingError(f"Video processing failed: {exc}") from exc
        processing_time = self._clock() - started_at

        return VideoProcessingResult(
            input_file=source,
            output_file=destination,
            profile=profile,
            processing_time=processing_time,
            ffmpeg_command=command,
        )

    @staticmethod
    def _validate_container(path: Path, label: str) -> None:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_VIDEO_CONTAINERS:
            supported = ", ".join(sorted(SUPPORTED_VIDEO_CONTAINERS))
            raise UnsupportedVideoFormatError(
                f"{label} video container '{suffix or '<none>'}' is unsupported. "
                f"Supported containers: {supported}."
            )
