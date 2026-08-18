"""End-to-end tests using real FFmpeg, ffprobe, and ExifTool processes."""

import subprocess
import sys
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from core.processor import MediaProcessor
from core.video import VideoProcessingError, VideoProcessor
from engines.exiftool import read_metadata
from engines.ffmpeg import MediaToolError, probe_file, run_ffmpeg
from models.profile import VideoProcessingProfile

pytestmark = pytest.mark.integration


def _profile(
    *,
    fps: float = 29.97,
    speed: float = 1.024,
    zoom: int = 1,
) -> VideoProcessingProfile:
    return VideoProcessingProfile(
        device_model="iPhone 14 Pro",
        creation_date=datetime(2026, 8, 9, 5, 59, 11),
        brightness=0.01,
        contrast=1.02,
        saturation=0.98,
        sharpness=0.36,
        noise_level=2,
        fps=fps,
        speed_multiplier=speed,
        zoom_percent=zoom,
        crf=24,
    )


def _stream(probe: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    return next(
        (
            stream
            for stream in probe.get("streams", [])
            if stream.get("codec_type") == codec_type
        ),
        None,
    )


def _fps(stream: dict[str, Any]) -> float:
    return float(Fraction(stream["avg_frame_rate"]))


def _duration(stream: dict[str, Any]) -> float:
    return float(stream["duration"])


def _metadata_values(metadata: dict[str, Any], tag_name: str) -> list[Any]:
    return [
        value
        for key, value in metadata.items()
        if key.rsplit(":", maxsplit=1)[-1] == tag_name
    ]


def _assert_decodes(path: Path) -> None:
    run_ffmpeg(("-v", "error", "-i", str(path), "-f", "null", "-"))


@pytest.mark.parametrize(
    ("fixture_name", "suffix", "profile"),
    (
        ("vertical", ".mp4", _profile(fps=24.0, speed=1.1, zoom=1)),
        ("horizontal", ".mp4", _profile(fps=29.97, speed=0.9, zoom=2)),
        ("no_audio", ".mp4", _profile(fps=30.0, speed=1.1, zoom=1)),
        ("mov", ".mov", _profile(fps=25.0, speed=0.9, zoom=2)),
    ),
)
def test_real_pipeline_preserves_media_contract(
    generated_videos: dict[str, Path],
    tmp_path: Path,
    fixture_name: str,
    suffix: str,
    profile: VideoProcessingProfile,
) -> None:
    source = generated_videos[fixture_name]
    output = tmp_path / f"processed{suffix}"
    input_probe = probe_file(source)

    result = VideoProcessor().process(source, output, profile)

    assert result.output_file == output
    assert output.is_file() and output.stat().st_size > 0
    _assert_decodes(output)
    output_probe = probe_file(output)
    input_video = _stream(input_probe, "video")
    output_video = _stream(output_probe, "video")
    assert input_video is not None
    assert output_video is not None
    assert output_video["codec_name"] == "h264"
    assert output_video["pix_fmt"] == "yuv420p"
    assert output_video["width"] == input_video["width"]
    assert output_video["height"] == input_video["height"]
    assert output_video.get("sample_aspect_ratio") in {None, "1:1"}
    assert output_video["width"] % 2 == 0
    assert output_video["height"] % 2 == 0
    assert _fps(output_video) == pytest.approx(profile.fps, abs=0.01)
    expected_duration = _duration(input_video) / profile.speed_multiplier
    duration_tolerance = max(0.08, 2 / profile.fps)
    output_video_duration = _duration(output_video)
    assert output_video_duration == pytest.approx(
        expected_duration,
        abs=duration_tolerance,
    )
    if profile.speed_multiplier > 1:
        assert output_video_duration < _duration(input_video)
    else:
        assert output_video_duration > _duration(input_video)

    input_audio = _stream(input_probe, "audio")
    output_audio = _stream(output_probe, "audio")
    assert (output_audio is not None) is (input_audio is not None)
    if output_audio is not None:
        assert input_audio is not None
        assert abs(output_video_duration - _duration(output_audio)) < 0.08
        expected_audio_duration = _duration(input_audio) / profile.speed_multiplier
        assert _duration(output_audio) == pytest.approx(
            expected_audio_duration,
            abs=0.06,
        )

    filter_graph = result.ffmpeg_command[
        result.ffmpeg_command.index("-filter_complex") + 1
    ]
    required_filters = (
        "scale=",
        "crop=",
        "setsar=",
        "eq=",
        "unsharp=",
        "noise=",
        "fps=",
        "setpts=",
    )
    for filter_name in required_filters:
        assert filter_name in filter_graph
    assert "pad=" not in filter_graph
    if input_audio is not None:
        audio_speed = result.ffmpeg_command[
            result.ffmpeg_command.index("-filter:a") + 1
        ]
        assert audio_speed == f"atempo={profile.speed_multiplier:.3f}"
        assert f"setpts=PTS/{profile.speed_multiplier:.3f}" in filter_graph


def test_metadata_is_replaced_with_profile_values(
    generated_videos: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = generated_videos["vertical"]
    output = tmp_path / "metadata_result.mp4"
    profile = _profile(fps=30.0)
    before = read_metadata(source)

    VideoProcessor().process(source, output, profile)

    after = read_metadata(output)
    assert "Legacy Title" in _metadata_values(before, "Title")
    assert "Legacy Comment" in _metadata_values(before, "Comment")
    assert "Legacy Artist" in _metadata_values(before, "Artist")
    assert not _metadata_values(after, "Title")
    assert not _metadata_values(after, "Comment")
    assert not _metadata_values(after, "Artist")
    assert _metadata_values(after, "Model") == [profile.device_model]
    creation_dates = _metadata_values(after, "CreationDate")
    assert len(creation_dates) == 1
    assert str(creation_dates[0]).startswith("2026:08:09 05:59:11")
    _assert_decodes(output)


def test_seeded_profiles_are_reproducible_and_process_successfully(
    generated_videos: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = generated_videos["horizontal"]
    first = MediaProcessor.with_seed(42).build_plan(source).profile
    repeated = MediaProcessor.with_seed(42).build_plan(source).profile
    assert first == repeated

    profiles: list[VideoProcessingProfile] = []
    for seed in (1, 42, 123):
        processor = MediaProcessor.with_seed(seed)
        plan = processor.build_plan(source)
        assert isinstance(plan.profile, VideoProcessingProfile)
        profiles.append(plan.profile)
        result = processor.process(plan, tmp_path / f"seed_{seed}.mp4")
        _assert_decodes(result.output_file)
    assert len(set(profiles)) == 3


@pytest.mark.parametrize(
    ("fixture_name", "output_name"),
    (
        ("spaces", "output with spaces.mp4"),
        ("unicode", "результат обработки.mp4"),
    ),
)
def test_paths_with_spaces_and_unicode(
    generated_videos: dict[str, Path],
    tmp_path: Path,
    fixture_name: str,
    output_name: str,
) -> None:
    result = VideoProcessor().process(
        generated_videos[fixture_name],
        tmp_path / output_name,
        _profile(),
    )
    _assert_decodes(result.output_file)


def test_very_short_video(
    generated_videos: dict[str, Path],
    tmp_path: Path,
) -> None:
    output = tmp_path / "short_result.mp4"
    VideoProcessor().process(
        generated_videos["very_short"],
        output,
        _profile(fps=30.0),
    )
    probe = probe_file(output)
    video = _stream(probe, "video")
    assert video is not None
    assert _duration(video) > 0
    _assert_decodes(output)


def test_expected_processor_errors_are_clear(
    generated_videos: dict[str, Path],
    tmp_path: Path,
) -> None:
    processor = VideoProcessor()
    profile = _profile()
    with pytest.raises(FileNotFoundError, match="does not exist"):
        processor.process(tmp_path / "missing.mp4", tmp_path / "out.mp4", profile)

    existing = tmp_path / "existing.mp4"
    existing.touch()
    with pytest.raises(FileExistsError, match="already exists"):
        processor.process(generated_videos["horizontal"], existing, profile)

    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a valid mp4")
    with pytest.raises(MediaToolError, match="failed with exit code"):
        processor.process(corrupt, tmp_path / "corrupt_out.mp4", profile)


def test_cli_expected_errors_have_no_traceback(
    generated_videos: dict[str, Path],
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    corrupt = tmp_path / "broken.mp4"
    corrupt.write_bytes(b"broken")
    existing = tmp_path / "already_here.mp4"
    existing.touch()
    cases = (
        (tmp_path / "missing.mp4", tmp_path / "missing_out.mp4"),
        (corrupt, tmp_path / "broken_out.mp4"),
        (generated_videos["horizontal"], existing),
    )
    for source, output in cases:
        completed = subprocess.run(
            [
                sys.executable,
                str(project_root / "cli.py"),
                str(source),
                "--output",
                str(output),
                "--seed",
                "42",
            ],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 1
        assert "ERROR" in completed.stderr
        assert "Traceback" not in completed.stderr


def test_cli_explicit_apple_device_processes_video_and_writes_metadata(
    generated_videos: dict[str, Path],
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "explicit_apple.mp4"

    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "cli.py"),
            str(generated_videos["horizontal"]),
            "--output",
            str(output),
            "--device",
            "iPhone 14 Pro",
            "--seed",
            "42",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "📱 Device: iPhone 14 Pro" in completed.stdout
    _assert_decodes(output)
    metadata = read_metadata(output)
    assert _metadata_values(metadata, "Make") == ["Apple"]
    assert _metadata_values(metadata, "Model") == ["iPhone 14 Pro"]
