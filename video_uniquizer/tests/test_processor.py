"""Tests for application-level media orchestration."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from core.params import ProfileGenerator
from core.processor import (
    MediaInfo,
    MediaKind,
    MediaProcessor,
    ProcessingPlan,
    UnsupportedMediaError,
)
from core.video import VideoProcessingResult
from models.image import ImageProcessingResult
from models.profile import ImageProcessingProfile, VideoProcessingProfile


def test_build_image_plan(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.jpg"
    Image.new("RGB", (320, 240), "blue").save(image_path)
    processor = MediaProcessor.with_seed(7)

    plan = processor.build_plan(image_path)

    assert plan.media.kind is MediaKind.IMAGE
    assert plan.media.properties["width"] == 320
    assert plan.media.properties["height"] == 240
    assert isinstance(plan.profile, ImageProcessingProfile)


@patch("core.processor.inspect_video")
def test_build_video_plan(mock_inspect: Mock, tmp_path: Path) -> None:
    video_path = tmp_path / "sample.mp4"
    video_path.touch()
    mock_inspect.return_value = {"codec": "H.264", "fps": 29.97}

    plan = MediaProcessor(ProfileGenerator()).build_plan(video_path)

    assert plan.media.kind is MediaKind.VIDEO
    assert isinstance(plan.profile, VideoProcessingProfile)


def test_rejects_unknown_extension(tmp_path: Path) -> None:
    media = tmp_path / "sample.txt"
    media.write_text("not media", encoding="utf-8")

    with pytest.raises(UnsupportedMediaError, match="Unsupported"):
        MediaProcessor().build_plan(media)


def test_process_delegates_image_plan(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    Image.new("RGB", (8, 8)).save(image_path)
    image_processor = Mock()
    processor = MediaProcessor(
        ProfileGenerator(),
        image_processor=image_processor,
    )
    plan = processor.build_plan(image_path)
    expected = ImageProcessingResult(
        input_file=image_path.resolve(),
        output_file=tmp_path / "output.png",
        profile=plan.profile,
        processing_time=0.1,
        width=8,
        height=8,
        output_format="PNG",
    )
    image_processor.process.return_value = expected

    result = processor.process(plan, tmp_path / "output.png")

    assert result is expected
    image_processor.process.assert_called_once_with(
        image_path.resolve(),
        tmp_path / "output.png",
        plan.profile,
    )


def test_process_accepts_image_path_directly(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.jpg"
    output_path = tmp_path / "output.jpg"
    Image.new("RGB", (12, 10)).save(image_path)
    image_processor = Mock()
    processor = MediaProcessor(image_processor=image_processor)
    image_processor.process.return_value = Mock()

    processor.process(image_path, output_path=output_path)

    call = image_processor.process.call_args
    assert call.args[0] == image_path.resolve()
    assert call.args[1] == output_path
    assert isinstance(call.args[2], ImageProcessingProfile)


def test_process_delegates_video_plan(tmp_path: Path) -> None:
    video_path = (tmp_path / "input.mp4").resolve()
    video_path.touch()
    output_path = tmp_path / "result.mp4"
    profile = ProfileGenerator().generate_video_profile()
    plan = ProcessingPlan(
        media=MediaInfo(
            path=video_path,
            kind=MediaKind.VIDEO,
            size_bytes=0,
            properties={"audio_streams": 1},
        ),
        profile=profile,
    )
    expected = VideoProcessingResult(
        input_file=video_path,
        output_file=output_path,
        profile=profile,
        processing_time=1.0,
        ffmpeg_command=("ffmpeg",),
    )
    video_processor = Mock()
    video_processor.process.return_value = expected
    processor = MediaProcessor(video_processor=video_processor)

    result = processor.process(plan, output_path)

    assert result is expected
    video_processor.process.assert_called_once_with(
        video_path,
        output_path,
        profile,
        has_audio=True,
    )
