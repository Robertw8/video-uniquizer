"""Tests for normalization of ffprobe video data."""

import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from engines.ffmpeg import MediaToolExecutionError
from models.profile import VideoProcessingProfile

from core.video import (
    UnsupportedVideoFormatError,
    VideoProcessingError,
    VideoProcessor,
    build_filter_complex,
    get_video_info,
    inspect_video,
)


@pytest.fixture
def video_profile() -> VideoProcessingProfile:
    return VideoProcessingProfile(
        device_model="iPhone 14 Pro",
        creation_date=datetime(2026, 8, 9, 5, 59, 11),
        brightness=0.01,
        contrast=1.0,
        saturation=0.99,
        sharpness=0.36,
        noise_level=2,
        fps=29.97,
        speed_multiplier=1.024,
        zoom_percent=1,
        crf=24,
    )


@patch("core.video.probe_file")
def test_inspect_video_normalizes_probe_data(mock_probe: Mock, tmp_path: Path) -> None:
    mock_probe.return_value = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {
            "format_name": "mov,mp4",
            "duration": "12.3456",
            "bit_rate": "8100000",
        },
    }

    info = inspect_video(tmp_path / "sample.mp4")

    assert info["fps"] == 29.97
    assert info["duration_seconds"] == 12.346
    assert info["codec"] == "h264"
    assert info["bitrate"] == 8_100_000
    assert info["audio_streams"] == 1


@patch("core.video.probe_file")
def test_get_video_info_returns_typed_details(
    mock_probe: Mock,
    tmp_path: Path,
) -> None:
    mock_probe.return_value = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "30/1",
                "bit_rate": "4000000",
                "duration": "5.5",
            }
        ],
        "format": {},
    }

    info = get_video_info(tmp_path / "sample.mov")

    assert (info.width, info.height) == (1280, 720)
    assert info.fps == 30.0
    assert info.duration_seconds == 5.5
    assert info.codec == "h264"
    assert info.bitrate == 4_000_000


def test_filter_complex_has_required_order(
    video_profile: VideoProcessingProfile,
) -> None:
    filter_graph = build_filter_complex(video_profile)

    expected_filters = (
        "scale=",
        "crop=",
        "setsar=",
        "eq=",
        "unsharp=",
        "noise=",
        "setpts=",
        "fps=",
    )
    positions = [filter_graph.index(item) for item in expected_filters]
    assert positions == sorted(positions)
    assert filter_graph.startswith("[0:v:0]")
    assert filter_graph.endswith("[video]")


def test_build_ffmpeg_command_uses_h264_and_audio_speed(
    video_profile: VideoProcessingProfile,
) -> None:
    processor = VideoProcessor(metadata_service=Mock())

    command = processor.build_ffmpeg_command(
        "input.mp4",
        "result.mov",
        video_profile,
        has_audio=True,
    )

    assert command[0] == "ffmpeg"
    assert command[command.index("-i") + 1] == "input.mp4"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-crf") + 1] == "24"
    assert command[command.index("-filter:a") + 1] == "atempo=1.024"
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "setpts=PTS/1.024,fps=29.97" in filter_graph
    assert command[-1] == "result.mov"


def test_process_returns_result_and_updates_metadata(
    video_profile: VideoProcessingProfile,
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.mp4"
    source.touch()
    destination = tmp_path / "result.mp4"
    runner = Mock(
        return_value=subprocess.CompletedProcess(["ffmpeg"], 0, "", "")
    )
    metadata_service = Mock()
    clock = Mock(side_effect=(10.0, 12.5))
    processor = VideoProcessor(runner, metadata_service, clock)

    result = processor.process(
        source,
        destination,
        video_profile,
        has_audio=False,
    )

    runner.assert_called_once_with(result.ffmpeg_command)
    metadata_service.replace.assert_called_once_with(
        destination,
        {
            "UserData:Make": "Apple",
            "UserData:Model": "iPhone 14 Pro",
            "Keys:CreationDate": "2026:08:09 05:59:11",
        },
    )
    assert result.input_file == source
    assert result.output_file == destination
    assert result.processing_time == 2.5
    assert "-filter:a" not in result.ffmpeg_command


def test_process_wraps_ffmpeg_errors(
    video_profile: VideoProcessingProfile,
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.mp4"
    source.touch()
    tool_error = MediaToolExecutionError("encoder failed")
    runner = Mock(side_effect=tool_error)
    metadata_service = Mock()
    processor = VideoProcessor(runner, metadata_service)

    with pytest.raises(VideoProcessingError, match="encoder failed"):
        processor.process(
            source,
            tmp_path / "result.mp4",
            video_profile,
            has_audio=False,
        )
    metadata_service.replace.assert_not_called()


def test_rejects_unsupported_output_container(
    video_profile: VideoProcessingProfile,
) -> None:
    processor = VideoProcessor(metadata_service=Mock())

    with pytest.raises(UnsupportedVideoFormatError, match="unsupported"):
        processor.build_ffmpeg_command(
            "input.mp4",
            "result.webm",
            video_profile,
            has_audio=False,
        )
