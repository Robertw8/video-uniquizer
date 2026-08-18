"""Telegram/FSM workflow for selecting, processing, and sending a batch."""

import asyncio
import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from bot.config import BotConfig
from bot.messages import (
    ACTIVE_PROCESS,
    BATCH_CANCELLED,
    BATCH_DELIVERY_COMPLETE,
    BATCH_DELIVERY_PARTIAL,
    BATCH_PROGRESS,
    BATCH_STARTED,
    CHOOSE_COPIES,
    FILE_TOO_LARGE,
    MAX_COPIES_EXCEEDED,
    PROCESSING_ERROR,
)

from .batch_processing import BatchProcessor, BatchProgress
from .batch_report import format_batch_copy_report
from .processing import IncomingMedia, ProcessingResult, TelegramMediaKind

logger = logging.getLogger(__name__)


class BatchWorkflowService:
    """Bridge Telegram updates and the reusable BatchProcessor."""

    def __init__(
        self,
        config: BotConfig,
        batch_processor: BatchProcessor,
        *,
        progress_interval: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_copies = config.max_copies
        self._max_file_size_bytes = config.max_file_size_bytes
        self._batch_processor = batch_processor
        self._progress_interval = progress_interval
        self._clock = clock
        self._active_users: set[int] = set()
        self._temp_directories: set[Path] = set()

    @property
    def max_copies(self) -> int:
        """Return the configured copy limit used by handlers and validation."""
        return self._max_copies

    async def prepare(
        self,
        bot: Bot,
        message: Message,
        media: IncomingMedia,
        state: FSMContext,
        keyboard: InlineKeyboardMarkup,
        awaiting_state: State,
    ) -> bool:
        """Download one input and retain its temporary path until selection."""
        user_id = self._message_user_id(message)
        if user_id in self._active_users:
            await message.answer(ACTIVE_PROCESS)
            return False
        if self._is_too_large(media.file_size):
            await message.answer(FILE_TOO_LARGE)
            return False

        self._active_users.add(user_id)
        temp_directory = Path(tempfile.mkdtemp(prefix="video_uniquizer_batch_"))
        self._temp_directories.add(temp_directory)
        input_path = temp_directory / f"input{media.extension}"
        try:
            await bot.download(media.file_id, destination=input_path)
            if not input_path.is_file():
                raise FileNotFoundError("Telegram download did not create a file.")
            await state.update_data(
                input_path=str(input_path),
                temp_directory=str(temp_directory),
                original_filename=media.original_filename,
                media_kind=media.kind.value,
                extension=media.extension,
                telegram_user_id=user_id,
                copies=None,
            )
            await state.set_state(awaiting_state)
            await message.answer(CHOOSE_COPIES, reply_markup=keyboard)
            logger.info(
                "Prepared batch user_id=%s media_type=%s size=%s",
                user_id,
                media.kind.value,
                media.file_size,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to prepare batch user_id=%s media_type=%s size=%s",
                user_id,
                media.kind.value,
                media.file_size,
            )
            await self._cleanup(user_id, temp_directory, state)
            await self._notify_error(message)
            return False

    async def run_batch(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        copies: int,
        processing_state: State,
    ) -> None:
        """Start streaming batch delivery from a quick-choice callback."""
        message = callback.message
        if message is None:
            await callback.answer()
            return
        message = cast(Message, message)
        if copies < 1:
            await callback.answer("Некорректное количество копий.", show_alert=True)
            return
        if copies > self._max_copies:
            await callback.answer(
                MAX_COPIES_EXCEEDED.format(max_copies=self._max_copies),
                show_alert=True,
            )
            return

        await callback.answer()
        await self._execute_batch(
            message,
            state,
            copies,
            processing_state,
            user_id=callback.from_user.id,
            edit_start_message=True,
        )

    async def run_batch_from_message(
        self,
        message: Message,
        state: FSMContext,
        copies: int,
        processing_state: State,
    ) -> None:
        """Start the same streaming batch flow after manual text input."""
        if copies < 1 or copies > self._max_copies:
            raise ValueError("Copy count is outside the configured range.")
        await self._execute_batch(
            message,
            state,
            copies,
            processing_state,
            user_id=self._message_user_id(message),
            edit_start_message=False,
        )

    async def _execute_batch(
        self,
        message: Message,
        state: FSMContext,
        copies: int,
        processing_state: State,
        *,
        user_id: int,
        edit_start_message: bool,
    ) -> None:
        """Generate copies and deliver each successful result immediately."""
        await state.set_state(processing_state)
        data = await state.get_data()
        temp_directory = Path(str(data.get("temp_directory", "")))
        try:
            input_path = Path(str(data["input_path"]))
            kind = TelegramMediaKind(str(data["media_kind"]))
            if not input_path.is_file() or not temp_directory.is_dir():
                raise FileNotFoundError("Prepared batch input no longer exists.")
            await state.update_data(copies=copies)
            if edit_start_message:
                await message.edit_text(BATCH_STARTED.format(copies=copies))
                progress_message = message
            else:
                progress_message = cast(
                    Message,
                    await message.answer(BATCH_STARTED.format(copies=copies)),
                )
            output_directory = temp_directory / "outputs"
            reporter = _ProgressReporter(
                progress_message,
                interval=self._progress_interval,
                clock=self._clock,
            )
            sent = 0
            delivery_failures = 0

            async def deliver_result(
                index: int,
                processing_result: ProcessingResult,
            ) -> None:
                nonlocal sent, delivery_failures
                try:
                    await message.answer(
                        format_batch_copy_report(index, processing_result)
                    )
                    await message.answer_document(
                        document=FSInputFile(
                            processing_result.output_file,
                            filename=processing_result.output_file.name,
                        )
                    )
                    sent += 1
                except Exception:
                    delivery_failures += 1
                    logger.exception(
                        "Could not deliver batch copy user_id=%s index=%s",
                        user_id,
                        index,
                    )
                finally:
                    processing_result.output_file.unlink(missing_ok=True)

            result = await self._batch_processor.generate_copies(
                input_path,
                copies,
                output_directory,
                output_prefix=(
                    "video_unique"
                    if kind is TelegramMediaKind.VIDEO
                    else "image_unique"
                ),
                progress_callback=reporter,
                result_callback=deliver_result,
            )
            failed = result.failed + delivery_failures
            summary = (
                BATCH_DELIVERY_COMPLETE.format(
                    completed=sent,
                    total=result.total,
                )
                if failed == 0
                else BATCH_DELIVERY_PARTIAL.format(
                    completed=sent,
                    total=result.total,
                    failed=failed,
                )
            )
            await message.answer(summary)
            logger.info(
                "Completed batch user_id=%s total=%s created=%s sent=%s failed=%s duration=%.3f",
                user_id,
                result.total,
                result.completed,
                sent,
                failed,
                result.processing_time,
            )
        except Exception:
            logger.exception("Batch workflow failed user_id=%s copies=%s", user_id, copies)
            await self._notify_error(message)
        finally:
            await self._cleanup(user_id, temp_directory, state)

    async def cancel(self, message: Message, state: FSMContext) -> None:
        """Cancel a pending selection and remove its retained input file."""
        data = await state.get_data()
        user_id = self._message_user_id(message)
        temp_directory = Path(str(data.get("temp_directory", "")))
        await self._cleanup(user_id, temp_directory, state)
        await message.answer(BATCH_CANCELLED)

    async def close(self) -> None:
        """Remove retained directories when long polling shuts down."""
        directories = tuple(self._temp_directories)
        self._temp_directories.clear()
        self._active_users.clear()
        await asyncio.gather(
            *(asyncio.to_thread(shutil.rmtree, path, True) for path in directories)
        )

    async def _cleanup(
        self,
        user_id: int,
        temp_directory: Path,
        state: FSMContext,
    ) -> None:
        self._active_users.discard(user_id)
        if temp_directory in self._temp_directories:
            self._temp_directories.discard(temp_directory)
            await asyncio.to_thread(shutil.rmtree, temp_directory, True)
        await state.clear()

    def _is_too_large(self, file_size: int | None) -> bool:
        return (
            self._max_file_size_bytes is not None
            and file_size is not None
            and file_size > self._max_file_size_bytes
        )

    @staticmethod
    def _message_user_id(message: Message) -> int:
        return message.from_user.id if message.from_user is not None else message.chat.id

    @staticmethod
    async def _notify_error(message: Message) -> None:
        try:
            await message.answer(PROCESSING_ERROR)
        except Exception:
            logger.warning("Could not deliver the batch error message", exc_info=True)


class _ProgressReporter:
    """Throttle Telegram progress edits while always emitting the final state."""

    def __init__(
        self,
        message: Message,
        *,
        interval: float,
        clock: Callable[[], float],
    ) -> None:
        self._message = message
        self._interval = interval
        self._clock = clock
        self._last_update = clock()

    async def __call__(self, progress: BatchProgress) -> None:
        now = self._clock()
        if (
            progress.processed < progress.total
            and now - self._last_update < self._interval
        ):
            return
        try:
            await self._message.edit_text(
                BATCH_PROGRESS.format(
                    completed=progress.completed,
                    total=progress.total,
                )
            )
            self._last_update = now
        except Exception:
            logger.warning("Could not update batch progress", exc_info=True)
