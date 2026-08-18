"""Async Telegram adapter around the synchronous MediaProcessor."""

import asyncio
import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from aiogram import Bot
from aiogram.types import FSInputFile, Message

from bot.config import BotConfig
from bot.messages import (
    ACTIVE_JOB,
    FILE_RECEIVED,
    FILE_TOO_LARGE,
    PROCESSING_ERROR,
    PROCESSING_STARTED,
    format_processing_result,
)
from core.processor import MediaProcessor
from models.image import ImageProcessingResult
from models.video import VideoProcessingResult

logger = logging.getLogger(__name__)

ProcessingResult = VideoProcessingResult | ImageProcessingResult
ProcessorFactory = Callable[[], MediaProcessor]


class AsyncLimiter(Protocol):
    """Minimal async context-manager contract implemented by Semaphore."""

    async def __aenter__(self) -> object: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool | None: ...


class TelegramMediaKind(str, Enum):
    """Media categories accepted from Telegram updates."""

    VIDEO = "video"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class IncomingMedia:
    """Normalized Telegram file data required by the processing service."""

    file_id: str
    file_unique_id: str
    kind: TelegramMediaKind
    extension: str
    file_size: int | None = None
    original_filename: str | None = None


def build_output_filename(media: IncomingMedia) -> str:
    """Build a readable Telegram filename without using it as a local path."""
    source_name = media.original_filename
    if source_name:
        leaf = source_name.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
        stem = Path(leaf).stem
        clean_stem = "".join(
            character
            for character in stem
            if character.isprintable() and character not in {"/", "\\", "\x00"}
        ).strip(" .")
    else:
        clean_stem = ""

    if not clean_stem:
        prefix = "video" if media.kind is TelegramMediaKind.VIDEO else "photo"
        safe_id = "".join(
            character
            for character in media.file_unique_id
            if character.isalnum() or character in {"-", "_"}
        )
        clean_stem = f"{prefix}_{safe_id or 'file'}"
    return f"{clean_stem}_unique{media.extension}"


class ProcessingService:
    """Download, process, upload, and clean one Telegram media job."""

    def __init__(
        self,
        config: BotConfig,
        processor_factory: ProcessorFactory = MediaProcessor,
        limiter: AsyncLimiter | None = None,
    ) -> None:
        self._max_file_size_bytes = config.max_file_size_bytes
        self._processor_factory = processor_factory
        self._limiter = limiter or asyncio.Semaphore(config.max_concurrent_jobs)
        self._active_users: set[int] = set()

    async def process(
        self,
        bot: Bot,
        message: Message,
        media: IncomingMedia,
    ) -> None:
        """Run one complete Telegram job and keep all artifacts temporary."""
        user_id = message.from_user.id if message.from_user is not None else message.chat.id
        if user_id in self._active_users:
            await message.answer(ACTIVE_JOB)
            return

        self._active_users.add(user_id)
        try:
            if self._is_too_large(media.file_size):
                logger.info(
                    "Rejected oversized upload user_id=%s media_type=%s size=%s",
                    user_id,
                    media.kind.value,
                    media.file_size,
                )
                await message.answer(FILE_TOO_LARGE)
                return

            logger.info(
                "Received job user_id=%s media_type=%s size=%s",
                user_id,
                media.kind.value,
                media.file_size,
            )
            status = await message.answer(FILE_RECEIVED)
            with tempfile.TemporaryDirectory(prefix="video_uniquizer_bot_") as temp:
                temp_path = Path(temp)
                input_path = temp_path / f"input{media.extension}"
                output_path = temp_path / f"output{media.extension}"
                await bot.download(media.file_id, destination=input_path)
                if not input_path.is_file():
                    raise FileNotFoundError("Telegram download did not create a file.")

                async with self._limiter:
                    await status.edit_text(PROCESSING_STARTED)
                    logger.info(
                        "Started processing user_id=%s media_type=%s size=%s",
                        user_id,
                        media.kind.value,
                        media.file_size,
                    )
                    started_at = time.perf_counter()
                    result = await asyncio.to_thread(
                        self._process_sync,
                        input_path,
                        output_path,
                    )
                    duration = time.perf_counter() - started_at

                document = FSInputFile(
                    output_path,
                    filename=build_output_filename(media),
                )
                await message.answer_document(
                    document=document,
                    caption=format_processing_result(result),
                )
                logger.info(
                    "Completed job user_id=%s media_type=%s size=%s duration=%.3f",
                    user_id,
                    media.kind.value,
                    media.file_size,
                    duration,
                )
        except Exception:
            logger.exception(
                "Failed job user_id=%s media_type=%s size=%s",
                user_id,
                media.kind.value,
                media.file_size,
            )
            await self._notify_processing_error(message)
        finally:
            self._active_users.discard(user_id)

    def _process_sync(self, input_path: Path, output_path: Path) -> ProcessingResult:
        processor = self._processor_factory()
        plan = processor.build_plan(input_path)
        return processor.process(plan, output_path)

    def _is_too_large(self, file_size: int | None) -> bool:
        return (
            self._max_file_size_bytes is not None
            and file_size is not None
            and file_size > self._max_file_size_bytes
        )

    @staticmethod
    async def _notify_processing_error(message: Message) -> None:
        try:
            await message.answer(PROCESSING_ERROR)
        except Exception:
            logger.warning("Could not deliver the processing error message", exc_info=True)
