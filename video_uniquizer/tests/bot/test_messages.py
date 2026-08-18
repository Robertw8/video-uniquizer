"""Tests for Telegram result reports."""

from datetime import datetime
from pathlib import Path

from bot.messages import (
    METADATA_UPDATED,
    START_MESSAGE,
    format_image_properties,
    format_processing_result,
    format_video_properties,
)
from models.image import ImageProcessingResult
from models.profile import ImageProcessingProfile, VideoProcessingProfile
from models.video import VideoProcessingResult


def _video_result() -> VideoProcessingResult:
    profile = VideoProcessingProfile(
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
    return VideoProcessingResult(
        input_file=Path("input.mp4"),
        output_file=Path("output.mp4"),
        profile=profile,
        processing_time=1.2,
        ffmpeg_command=("ffmpeg", "secret-local-path"),
    )


def _image_result(output_format: str = "JPEG") -> ImageProcessingResult:
    profile = ImageProcessingProfile(
        device_model="Galaxy S23",
        creation_date=datetime(2026, 8, 9, 5, 59, 11),
        brightness=1.01,
        contrast=1.02,
        saturation=0.99,
        sharpness=0.4,
        noise_level=1,
        jpeg_quality=94,
        zoom_percent=1,
    )
    suffix = ".jpg" if output_format == "JPEG" else ".png"
    return ImageProcessingResult(
        input_file=Path(f"input{suffix}"),
        output_file=Path(f"output{suffix}"),
        profile=profile,
        processing_time=0.2,
        width=320,
        height=180,
        output_format=output_format,
    )


def test_start_message_describes_all_supported_formats() -> None:
    assert "👋 Привет!" in START_MESSAGE
    for extension in ("MP4", "MOV", "JPG / JPEG", "PNG"):
        assert extension in START_MESSAGE


def test_video_result_report_uses_profile_without_internal_details() -> None:
    result = _video_result()
    report = format_processing_result(result)

    assert "✅ Видео успешно обработано!" in report
    assert "iPhone 14 Pro" in report
    assert "29.97" in report
    assert "1.024x" in report
    assert "CRF: 24" in report
    assert "ffmpeg" not in report
    assert "secret-local-path" not in report
    assert report == (
        "✅ Видео успешно обработано!\n\n"
        "📋 Применённые параметры:\n\n"
        f"{format_video_properties(result)}"
    )


def test_image_result_only_shows_jpeg_quality_for_jpeg() -> None:
    jpeg_result = _image_result()
    png_result = _image_result("PNG")

    assert "JPEG Quality: 94" in format_image_properties(jpeg_result)
    assert "JPEG Quality" not in format_image_properties(png_result)
    assert METADATA_UPDATED in format_image_properties(jpeg_result)
    assert METADATA_UPDATED in format_image_properties(png_result)
    assert format_processing_result(jpeg_result) == (
        "✅ Фото успешно обработано!\n\n"
        "📋 Применённые параметры:\n\n"
        f"{format_image_properties(jpeg_result)}"
    )
