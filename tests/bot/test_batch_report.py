"""Tests for complete vertical batch reports and Telegram splitting."""

from datetime import datetime
from pathlib import Path

from bot.messages import METADATA_UPDATED, format_processing_properties
from bot.services.batch_processing import BatchResult
from bot.services.batch_report import (
    format_batch_telegram_messages,
    format_batch_telegram_report,
    format_batch_text_report,
)
from bot.services.processing import ProcessingResult
from models.image import ImageProcessingResult
from models.profile import ImageProcessingProfile, VideoProcessingProfile
from models.video import VideoProcessingResult


def _video_result(index: int) -> VideoProcessingResult:
    output = Path(f"video_unique_{index:03d}.mp4")
    return VideoProcessingResult(
        input_file=Path("input.mp4"),
        output_file=output,
        profile=VideoProcessingProfile(
            device_model=f"Video Device {index}",
            creation_date=datetime(2026, 8, index, 10, 20, 30),
            brightness=0.01,
            contrast=0.99,
            saturation=1.02,
            sharpness=0.4,
            noise_level=2,
            fps=29.97,
            speed_multiplier=1.012,
            zoom_percent=1,
            crf=24,
        ),
        processing_time=0.2,
        ffmpeg_command=("ffmpeg",),
    )


def _image_result(
    index: int = 1,
    output_format: str = "JPEG",
) -> ImageProcessingResult:
    suffix = ".jpg" if output_format == "JPEG" else ".png"
    return ImageProcessingResult(
        input_file=Path(f"input{suffix}"),
        output_file=Path(f"image_unique_{index:03d}{suffix}"),
        profile=ImageProcessingProfile(
            device_model=f"Image Device {index}",
            creation_date=datetime(2026, 8, index, 11, 21, 31),
            brightness=1.01,
            contrast=0.98,
            saturation=1.03,
            sharpness=0.5,
            noise_level=3,
            jpeg_quality=91,
            zoom_percent=2,
        ),
        processing_time=0.1,
        width=640,
        height=480,
        output_format=output_format,
    )


def _batch(
    results: list[ProcessingResult],
    *,
    total: int | None = None,
) -> BatchResult:
    requested = total if total is not None else len(results)
    return BatchResult(
        total=requested,
        completed=len(results),
        failed=requested - len(results),
        output_files=tuple(item.output_file for item in results),
        results=results,
        processing_time=0.3,
        seeds=tuple(range(1, requested + 1)),
    )


def test_video_report_reuses_full_vertical_properties() -> None:
    result = _video_result(1)
    report = format_batch_telegram_report(_batch([result]))

    assert report.startswith(
        "✅ Готово!\n\n"
        "Создано: 1/1 уникальных копий\n\n"
        "📋 Применённые параметры:"
    )
    assert "━━━━━━━━━━\nКопия #1\n━━━━━━━━━━" in report
    assert format_processing_properties(result) in report
    assert "🎬 FPS: 29.97" in report
    assert "⚡ Скорость: 1.012x" in report
    assert "🎨 Цветокоррекция: C:0.99 | B:0.01 | S:1.02" in report
    assert "📊 CRF: 24" in report
    assert METADATA_UPDATED in report


def test_photo_report_matches_vertical_format_for_jpeg_and_png() -> None:
    jpeg = _image_result(1, "JPEG")
    png = _image_result(2, "PNG")
    report = format_batch_telegram_report(_batch([jpeg, png]))

    assert format_processing_properties(jpeg) in report
    assert format_processing_properties(png) in report
    assert "☀️ Яркость: 1.01" in report
    assert "🎨 Контраст: 0.98" in report
    assert "🌈 Насыщенность: 1.03" in report
    assert report.count("🖼 JPEG Quality: 91") == 1
    assert report.count(METADATA_UPDATED) == 2


def test_partial_report_contains_only_successful_results() -> None:
    results: list[ProcessingResult] = [_video_result(1), _video_result(2)]
    report = format_batch_telegram_report(_batch(results, total=3))

    assert report.startswith("⚠️ Создано 2 из 3 уникальных копий.")
    assert "Копия #1" in report
    assert "Копия #2" in report
    assert "Копия #3" not in report
    assert report.count(METADATA_UPDATED) == 2


def test_long_telegram_report_splits_without_losing_copy_blocks() -> None:
    results: list[ProcessingResult] = [
        _video_result(index) for index in range(1, 21)
    ]
    messages = format_batch_telegram_messages(
        _batch(results),
        message_limit=900,
    )

    assert len(messages) > 1
    assert all(len(message) <= 900 for message in messages)
    assert messages[0].startswith("✅ Готово!")
    for index, result in enumerate(results, start=1):
        complete_block = (
            f"━━━━━━━━━━\nКопия #{index}\n━━━━━━━━━━\n\n"
            f"{format_processing_properties(result)}"
        )
        assert sum(complete_block in message for message in messages) == 1


def test_text_report_contains_every_copy_without_shortening() -> None:
    results: list[ProcessingResult] = [
        _video_result(1),
        _image_result(2, "JPEG"),
        _image_result(3, "PNG"),
    ]
    report = format_batch_text_report(_batch(results))

    assert report.count("Копия #") == 3
    assert report.count(METADATA_UPDATED) == 3
    for result in results:
        assert format_processing_properties(result) in report
