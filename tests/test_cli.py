"""Tests for the thin command-line adapter."""

from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from cli import main
from core.image import ImageProcessingError
from core.video import VideoProcessingResult
from models.image import ImageProcessingResult
from models.profile import ImageProcessingProfile, VideoProcessingProfile


def test_cli_prints_file_info_and_profile(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image_path = tmp_path / "sample.jpg"
    Image.new("RGB", (64, 48), "green").save(image_path)

    exit_code = main(["--seed", "42", str(image_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Type: image" in output
    assert "Width: 64" in output
    assert "Generated processing profile" in output
    assert "JPEG quality:" in output


@patch("cli.MediaProcessor.with_seed")
def test_cli_processes_video_when_output_is_provided(
    mock_with_seed: Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "input.mp4"
    destination = tmp_path / "result.mp4"
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
    processor = Mock()
    plan = Mock()
    processor.build_plan.return_value = plan
    processor.process.return_value = VideoProcessingResult(
        input_file=source,
        output_file=destination,
        profile=profile,
        processing_time=1.5,
        ffmpeg_command=("ffmpeg",),
    )
    mock_with_seed.return_value = processor

    exit_code = main(
        [str(source), "--output", str(destination), "--seed", "42"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    processor.build_plan.assert_called_once_with(str(source))
    processor.process.assert_called_once_with(plan, str(destination))
    assert "✅ Видео успешно обработано" in output
    assert "📱 Device: iPhone 14 Pro" in output
    assert f"Output:\n{destination}" in output


@pytest.mark.parametrize(
    ("output_format", "suffix", "quality_visible"),
    (("JPEG", ".jpg", True), ("PNG", ".png", False)),
)
@patch("cli.MediaProcessor.with_seed")
def test_cli_formats_image_success(
    mock_with_seed: Mock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    output_format: str,
    suffix: str,
    quality_visible: bool,
) -> None:
    source = tmp_path / f"input{suffix}"
    destination = tmp_path / f"result{suffix}"
    profile = ImageProcessingProfile(
        device_model="iPhone 14 Pro",
        creation_date=datetime(2026, 8, 9, 5, 59, 11),
        brightness=1.01,
        contrast=1.02,
        saturation=0.99,
        sharpness=0.36,
        noise_level=2,
        jpeg_quality=94,
        zoom_percent=1,
    )
    processor = Mock()
    plan = Mock()
    processor.build_plan.return_value = plan
    processor.process.return_value = ImageProcessingResult(
        input_file=source,
        output_file=destination,
        profile=profile,
        processing_time=0.2,
        width=180,
        height=320,
        output_format=output_format,
    )
    mock_with_seed.return_value = processor

    exit_code = main(
        [str(source), "--output", str(destination), "--seed", "42"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "✅ Фото успешно обработано" in output
    assert "🗑 Старые metadata удалены" in output
    assert ("JPEG Quality" in output) is quality_visible
    assert f"Output:\n{destination}" in output


@patch("cli.MediaProcessor.with_seed")
def test_cli_expected_image_error_has_no_traceback(
    mock_with_seed: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    processor = Mock()
    processor.build_plan.return_value = Mock()
    processor.process.side_effect = ImageProcessingError("corrupt image")
    mock_with_seed.return_value = processor

    with caplog.at_level("ERROR"):
        exit_code = main(["broken.jpg", "--output", "result.jpg", "--seed", "1"])

    assert exit_code == 1
    assert "corrupt image" in caplog.text
    assert "Traceback" not in caplog.text


def test_cli_real_corrupt_image_has_no_traceback(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"broken image")

    with caplog.at_level("ERROR"):
        exit_code = main([str(corrupt), "--output", str(tmp_path / "result.jpg")])

    assert exit_code == 1
    assert "Cannot inspect image" in caplog.text
    assert "Traceback" not in caplog.text


def test_cli_explicit_device_generates_matching_profile(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image_path = tmp_path / "sample.jpg"
    Image.new("RGB", (64, 48), "blue").save(image_path)

    exit_code = main(
        [str(image_path), "--device", "Galaxy S23", "--seed", "42"]
    )

    assert exit_code == 0
    assert "Device: Galaxy S23" in capsys.readouterr().out


def test_cli_unknown_device_has_available_list_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR"):
        exit_code = main(["input.jpg", "--device", "Unknown Phone"])

    assert exit_code == 1
    assert "Unknown device: Unknown Phone" in caplog.text
    assert "Available devices:" in caplog.text
    assert "Traceback" not in caplog.text


def test_cli_lists_devices_without_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--list-devices"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Apple:\n  - iPhone 12" in output
    assert "Samsung:\n  - Galaxy S22" in output
