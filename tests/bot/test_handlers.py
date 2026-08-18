"""Tests for thin aiogram media and command handlers."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.types import Document, Message, PhotoSize, Video

from bot.handlers.media import (
    handle_document,
    handle_photo,
    handle_unsupported_message,
    handle_video,
)
from bot.handlers.start import handle_start
from bot.messages import START_MESSAGE, UNSUPPORTED_FILE, UNSUPPORTED_MESSAGE
from bot.services.processing import ProcessingService, TelegramMediaKind


def _message(**content: object) -> Message:
    values: dict[str, object] = {
        "answer": AsyncMock(),
        "video": None,
        "photo": None,
        "document": None,
    }
    values.update(content)
    return cast(Message, SimpleNamespace(**values))


def _bot() -> Bot:
    return cast(Bot, SimpleNamespace())


def _service() -> ProcessingService:
    return cast(ProcessingService, SimpleNamespace(process=AsyncMock()))


def test_start_handler() -> None:
    message = _message()

    asyncio.run(handle_start(message))

    message.answer.assert_awaited_once_with(START_MESSAGE) 


def test_video_handler_normalizes_native_video() -> None:
    video = Video(
        file_id="video-id",
        file_unique_id="video-unique",
        width=320,
        height=180,
        duration=2,
        file_size=1234,
    )
    message = _message(video=video)
    bot = _bot()
    service = _service()

    asyncio.run(handle_video(message, bot, service))

    media = service.process.await_args.args[2]
    assert media.kind is TelegramMediaKind.VIDEO
    assert media.extension == ".mp4"
    assert media.file_size == 1234


def test_photo_handler_uses_largest_available_photo() -> None:
    small = PhotoSize(
        file_id="small",
        file_unique_id="small-unique",
        width=90,
        height=90,
        file_size=100,
    )
    large = PhotoSize(
        file_id="large",
        file_unique_id="large-unique",
        width=1280,
        height=720,
        file_size=5000,
    )
    message = _message(photo=[large, small])
    service = _service()

    asyncio.run(handle_photo(message, _bot(), service))

    media = service.process.await_args.args[2] 
    assert media.file_id == "large"
    assert media.extension == ".jpg"
    assert media.kind is TelegramMediaKind.IMAGE


def test_image_document_handler() -> None:
    document = Document(
        file_id="image-id",
        file_unique_id="image-unique",
        file_name="family photo.JPEG",
        file_size=2000,
    )
    message = _message(document=document)
    service = _service()

    asyncio.run(handle_document(message, _bot(), service))

    media = service.process.await_args.args[2]
    assert media.kind is TelegramMediaKind.IMAGE
    assert media.extension == ".jpeg"
    assert media.original_filename == "family photo.JPEG"


def test_video_document_handler() -> None:
    document = Document(
        file_id="movie-id",
        file_unique_id="movie-unique",
        file_name="отпуск.mov",
    )
    message = _message(document=document)
    service = _service()

    asyncio.run(handle_document(message, _bot(), service))

    media = service.process.await_args.args[2]
    assert media.kind is TelegramMediaKind.VIDEO
    assert media.extension == ".mov"
    assert media.original_filename == "отпуск.mov"


def test_unsupported_document_gets_clear_reply() -> None:
    document = Document(
        file_id="archive-id",
        file_unique_id="archive-unique",
        file_name="archive.zip",
    )
    message = _message(document=document)
    service = _service()

    asyncio.run(handle_document(message, _bot(), service))

    message.answer.assert_awaited_once_with(UNSUPPORTED_FILE)
    service.process.assert_not_awaited()


def test_non_media_message_does_not_fail() -> None:
    message = _message()

    asyncio.run(handle_unsupported_message(message))

    message.answer.assert_awaited_once_with(UNSUPPORTED_MESSAGE)
