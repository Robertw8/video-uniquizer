"""Tests for asynchronous Telegram processing orchestration."""

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiogram import Bot
from aiogram.types import FSInputFile, Message

from bot.config import BotConfig
from bot.messages import ACTIVE_JOB, FILE_TOO_LARGE, PROCESSING_ERROR
from bot.services.processing import (
    IncomingMedia,
    ProcessingService,
    TelegramMediaKind,
    build_output_filename,
)
from core.processor import MediaProcessor
from core.video import VideoProcessingError
from models.profile import VideoProcessingProfile
from models.video import VideoProcessingResult


def _media(
    *,
    filename: str | None = "holiday.mp4",
    file_size: int | None = 1024,
) -> IncomingMedia:
    return IncomingMedia(
        file_id="telegram-file-id",
        file_unique_id="unique-42",
        kind=TelegramMediaKind.VIDEO,
        extension=".mp4",
        file_size=file_size,
        original_filename=filename,
    )


def _result(input_path: Path, output_path: Path) -> VideoProcessingResult:
    return VideoProcessingResult(
        input_file=input_path,
        output_file=output_path,
        profile=VideoProcessingProfile(
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
        ),
        processing_time=0.1,
        ffmpeg_command=("ffmpeg",),
    )


def _message(user_id: int = 100) -> Message:
    status = SimpleNamespace(edit_text=AsyncMock())
    return cast(
        Message,
        SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            chat=SimpleNamespace(id=user_id),
            answer=AsyncMock(return_value=status),
            answer_document=AsyncMock(),
        ),
    )


def _bot(download_error: Exception | None = None) -> Bot:
    async def download(_file_id: str, *, destination: Path) -> None:
        if download_error is not None:
            raise download_error
        destination.write_bytes(b"telegram media")

    return cast(Bot, SimpleNamespace(download=AsyncMock(side_effect=download)))


def _processor() -> tuple[MediaProcessor, Mock]:
    processor = Mock(spec=MediaProcessor)
    processor.build_plan.return_value = Mock()

    def process(_plan: object, output_path: Path) -> VideoProcessingResult:
        output_path.write_bytes(b"processed media")
        return _result(Path("input.mp4"), output_path)

    processor.process.side_effect = process
    return cast(MediaProcessor, processor), processor


def _service(
    processor: MediaProcessor,
    *,
    config: BotConfig | None = None,
    limiter: object | None = None,
) -> ProcessingService:
    return ProcessingService(
        config or BotConfig(token="test"),
        processor_factory=lambda: processor,
        limiter=limiter,
    )


def test_success_calls_media_processor_and_sends_document() -> None:
    processor, processor_mock = _processor()
    service = _service(processor)
    message = _message()

    asyncio.run(service.process(_bot(), message, _media()))

    processor_mock.build_plan.assert_called_once()
    processor_mock.process.assert_called_once()
    sent = message.answer_document.await_args.kwargs  
    assert isinstance(sent["document"], FSInputFile)
    assert sent["document"].filename == "holiday_unique.mp4"
    assert "✅ Видео успешно обработано!" in sent["caption"]


def test_processing_uses_asyncio_to_thread() -> None:
    processor, _ = _processor()
    service = _service(processor)

    async def run_sync(function: object, *args: object) -> object:
        return function(*args) 

    with patch(
        "bot.services.processing.asyncio.to_thread",
        new=AsyncMock(side_effect=run_sync),
    ) as to_thread:
        asyncio.run(service.process(_bot(), _message(), _media()))

    to_thread.assert_awaited_once()


class RecordingLimiter:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> object:
        self.entered += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self.exited += 1


def test_processing_uses_concurrency_limiter() -> None:
    processor, _ = _processor()
    limiter = RecordingLimiter()
    service = _service(processor, limiter=limiter)

    asyncio.run(service.process(_bot(), _message(), _media()))

    assert limiter.entered == 1
    assert limiter.exited == 1


def test_temporary_files_are_removed_after_upload() -> None:
    processor, _ = _processor()
    service = _service(processor)
    message = _message()

    asyncio.run(service.process(_bot(), message, _media()))

    document = message.answer_document.await_args.kwargs["document"]  
    assert isinstance(document, FSInputFile)
    assert not Path(document.path).exists()
    assert not Path(document.path).parent.exists()


@pytest.mark.parametrize(
    "processing_error",
    (ValueError("corrupt media"), VideoProcessingError("ffmpeg failed")),
)
def test_processing_and_corrupt_media_errors_are_hidden(
    processing_error: Exception,
) -> None:
    processor, processor_mock = _processor()
    processor_mock.build_plan.side_effect = processing_error
    service = _service(processor)
    message = _message()

    asyncio.run(service.process(_bot(), message, _media()))

    assert message.answer.await_args_list[-1].args == (PROCESSING_ERROR,)  
    message.answer_document.assert_not_awaited()  


def test_download_error_is_hidden() -> None:
    processor, _ = _processor()
    service = _service(processor)
    message = _message()

    asyncio.run(
        service.process(
            _bot(RuntimeError("telegram download failed")),
            message,
            _media(),
        )
    )

    assert message.answer.await_args_list[-1].args == (PROCESSING_ERROR,)  


def test_upload_error_still_cleans_temporary_files() -> None:
    processor, _ = _processor()
    service = _service(processor)
    message = _message()
    captured_path: Path | None = None

    async def fail_upload(*, document: FSInputFile, caption: str) -> None:
        nonlocal captured_path
        captured_path = Path(document.path)
        assert captured_path.exists()
        raise RuntimeError("telegram upload failed")

    message.answer_document.side_effect = fail_upload  
    asyncio.run(service.process(_bot(), message, _media()))

    assert captured_path is not None
    assert not captured_path.exists()
    assert message.answer.await_args_list[-1].args == (PROCESSING_ERROR,)  


def test_application_file_limit_is_checked_before_download() -> None:
    processor, processor_mock = _processor()
    service = _service(
        processor,
        config=BotConfig(token="test", max_file_size_mb=1),
    )
    bot = _bot()
    message = _message()

    asyncio.run(service.process(bot, message, _media(file_size=1_048_577)))

    message.answer.assert_awaited_once_with(FILE_TOO_LARGE)  
    bot.download.assert_not_awaited()  
    processor_mock.build_plan.assert_not_called()


def test_active_user_cannot_start_second_job() -> None:
    async def scenario() -> tuple[Message, Message]:
        processor, _ = _processor()
        service = _service(processor)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_download(_file_id: str, *, destination: Path) -> None:
            started.set()
            await release.wait()
            destination.write_bytes(b"telegram media")

        bot = cast(Bot, SimpleNamespace(download=AsyncMock(side_effect=slow_download)))
        first_message = _message(user_id=777)
        second_message = _message(user_id=777)
        first_job = asyncio.create_task(
            service.process(bot, first_message, _media())
        )
        await started.wait()
        await service.process(bot, second_message, _media())
        release.set()
        await first_job
        return first_message, second_message

    first_message, second_message = asyncio.run(scenario())

    first_message.answer_document.assert_awaited_once()  
    second_message.answer.assert_awaited_once_with(ACTIVE_JOB)  


@pytest.mark.parametrize(
    ("media", "expected"),
    (
        (_media(filename="summer holiday.mp4"), "summer holiday_unique.mp4"),
        (_media(filename="летний отпуск.mp4"), "летний отпуск_unique.mp4"),
        (_media(filename=None), "video_unique-42_unique.mp4"),
        (_media(filename="../../unsafe.mp4"), "unsafe_unique.mp4"),
        (_media(filename="folder\\clip.mp4"), "clip_unique.mp4"),
    ),
)
def test_output_filename_handling(media: IncomingMedia, expected: str) -> None:
    assert build_output_filename(media) == expected
