"""Tests for Telegram FSM batch selection, progress, archive, and cleanup."""

import asyncio
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.config import BotConfig
from bot.handlers.batch import BatchStates, copies_keyboard
from bot.messages import (
    ACTIVE_PROCESS,
    BATCH_CANCELLED,
    BATCH_DELIVERY_COMPLETE,
    BATCH_DELIVERY_PARTIAL,
    FILE_TOO_LARGE,
    MAX_COPIES_EXCEEDED,
    PROCESSING_ERROR,
)
from bot.services.batch_processing import BatchProcessor
from bot.services.batch_workflow import BatchWorkflowService
from bot.services.processing import IncomingMedia, TelegramMediaKind
from core.processor import MediaProcessor
from models.profile import VideoProcessingProfile
from models.video import VideoProcessingResult


class FakeProcessor:
    def __init__(self, seed: int, fail_even: bool = False) -> None:
        self.seed = seed
        self.fail_even = fail_even

    def build_plan(self, source: Path) -> Path:
        return source

    def process(self, plan: object, output_path: Path) -> VideoProcessingResult:
        if self.fail_even and self.seed % 2 == 0:
            raise RuntimeError("copy failed")
        output_path.write_text(str(self.seed), encoding="utf-8")
        source = cast(Path, plan)
        return VideoProcessingResult(
            input_file=source,
            output_file=output_path,
            profile=VideoProcessingProfile(
                device_model=f"Test Device {self.seed}",
                creation_date=datetime(2026, 8, 1, 12, 0),
                brightness=0.01,
                contrast=0.99,
                saturation=1.02,
                sharpness=0.4,
                noise_level=2,
                fps=29.97,
                speed_multiplier=1.01,
                zoom_percent=1,
                crf=24,
            ),
            processing_time=0.1,
            ffmpeg_command=("ffmpeg",),
        )


def _state(user_id: int = 100) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id),
    )


def _message(user_id: int = 100) -> Message:
    return cast(
        Message,
        SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            chat=SimpleNamespace(id=user_id),
            answer=AsyncMock(),
            edit_text=AsyncMock(),
            answer_document=AsyncMock(),
        ),
    )


def _bot() -> Bot:
    async def download(_file_id: str, *, destination: Path) -> None:
        destination.write_bytes(b"telegram input")

    return cast(Bot, SimpleNamespace(download=AsyncMock(side_effect=download)))


def _media(file_size: int = 100) -> IncomingMedia:
    return IncomingMedia(
        file_id="file-id",
        file_unique_id="unique-id",
        kind=TelegramMediaKind.VIDEO,
        extension=".mp4",
        file_size=file_size,
        original_filename="holiday.mp4",
    )


def _callback(message: Message, copies: int, user_id: int = 100) -> CallbackQuery:
    return cast(
        CallbackQuery,
        SimpleNamespace(
            data=f"batch:copies:{copies}",
            from_user=SimpleNamespace(id=user_id),
            message=message,
            answer=AsyncMock(),
        ),
    )


def _batch_processor(*, partial: bool = False) -> BatchProcessor:
    def factory(seed: int) -> MediaProcessor:
        return cast(MediaProcessor, FakeProcessor(seed, fail_even=partial))

    return BatchProcessor(
        max_copies=20,
        max_workers=2,
        processor_factory=factory,
        rng=random.Random(42),
    )


def _workflow(
    *,
    partial: bool = False,
    max_file_size_mb: float | None = None,
) -> BatchWorkflowService:
    return BatchWorkflowService(
        BotConfig(
            token="test",
            max_file_size_mb=max_file_size_mb,
            max_copies=20,
            max_batch_workers=2,
        ),
        _batch_processor(partial=partial),
        progress_interval=0,
    )


def test_prepare_downloads_input_saves_fsm_and_shows_keyboard() -> None:
    async def scenario() -> None:
        workflow = _workflow()
        state = _state()
        message = _message()
        keyboard = copies_keyboard()

        prepared = await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            keyboard,
            BatchStates.awaiting_copies,
        )

        data = await state.get_data()
        assert prepared is True
        assert await state.get_state() == BatchStates.awaiting_copies.state
        assert Path(data["input_path"]).is_file()
        assert data["telegram_user_id"] == 100
        assert data["media_kind"] == "video"
        assert data["copies"] is None
        assert message.answer.await_args.kwargs["reply_markup"] == keyboard 
        await workflow.cancel(message, state)

    asyncio.run(scenario())


def test_batch_streams_properties_files_summary_and_cleans_everything() -> None:
    async def scenario() -> tuple[Message, Path, FSMContext]:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        temp_directory = Path((await state.get_data())["temp_directory"])

        await workflow.run_batch(
            _callback(message, 5),
            state,
            5,
            BatchStates.processing,
        )
        return message, temp_directory, state

    message, temp_directory, state = asyncio.run(scenario())

    documents = [
        call.kwargs["document"]
        for call in message.answer_document.await_args_list 
    ]
    assert len(documents) == 5
    assert all(isinstance(document, FSInputFile) for document in documents)
    assert sorted(document.filename for document in documents) == [
        f"video_unique_{index:03d}.mp4" for index in range(1, 6)
    ]
    property_messages = [
        call.args[0]
        for call in message.answer.await_args_list 
        if call.args and call.args[0].startswith("━━━━━━━━━━")
    ]
    assert len(property_messages) == 5
    assert any("Копия #1" in report for report in property_messages)
    assert any("Копия #5" in report for report in property_messages)
    assert all("🎬 FPS: 29.97" in report for report in property_messages)
    assert all("🗑 Старые метаданные удалены" in report for report in property_messages)
    assert message.answer.await_args.args == ( 
        BATCH_DELIVERY_COMPLETE.format(completed=5, total=5),
    )
    assert message.edit_text.await_count >= 2 
    assert any(
        "5/5 готово" in call.args[0]
        for call in message.edit_text.await_args_list 
    )
    assert not temp_directory.exists()
    assert asyncio.run(state.get_state()) is None


def test_large_batch_streams_every_copy_without_zip() -> None:
    async def scenario() -> Message:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        await workflow.run_batch(
            _callback(message, 20),
            state,
            20,
            BatchStates.processing,
        )
        return message

    message = asyncio.run(scenario())
    property_messages = [
        call.args[0]
        for call in message.answer.await_args_list 
        if call.args and call.args[0].startswith("━━━━━━━━━━")
    ]

    assert len(property_messages) == 20
    assert message.answer_document.await_count == 20 
    combined = "\n".join(property_messages)
    for index in range(1, 21):
        assert combined.count(f"Копия #{index}\n") == 1
    assert combined.count("🗑 Старые метаданные удалены") == 20
    assert all(
        call.kwargs["document"].filename != "unique_pack.zip"
        for call in message.answer_document.await_args_list 
    )


def test_output_exists_during_upload_and_is_deleted_afterwards() -> None:
    async def scenario() -> tuple[list[Path], Path]:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        temp_directory = Path((await state.get_data())["temp_directory"])
        uploaded_paths: list[Path] = []

        async def inspect_upload(*, document: FSInputFile) -> None:
            path = Path(document.path)
            assert path.is_file()
            uploaded_paths.append(path)

        message.answer_document.side_effect = inspect_upload 
        await workflow.run_batch(
            _callback(message, 5),
            state,
            5,
            BatchStates.processing,
        )
        return uploaded_paths, temp_directory

    uploaded_paths, temp_directory = asyncio.run(scenario())
    assert len(uploaded_paths) == 5
    assert all(not path.exists() for path in uploaded_paths)
    assert not temp_directory.exists()


def test_partial_batch_streams_successes_and_sends_final_warning() -> None:
    async def scenario() -> Message:
        workflow = _workflow(partial=True)
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        await workflow.run_batch(
            _callback(message, 5),
            state,
            5,
            BatchStates.processing,
        )
        return message

    message = asyncio.run(scenario())
    sent = message.answer_document.await_count 
    assert 0 < sent < 5
    assert message.answer.await_args.args == ( 
        BATCH_DELIVERY_PARTIAL.format(
            completed=sent,
            total=5,
            failed=5 - sent,
        ),
    )


def test_manual_count_uses_the_same_streaming_delivery() -> None:
    async def scenario() -> tuple[Message, Path, FSMContext]:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        temp_directory = Path((await state.get_data())["temp_directory"])
        await state.set_state(BatchStates.waiting_for_custom_count)
        await workflow.run_batch_from_message(
            message,
            state,
            7,
            BatchStates.processing,
        )
        return message, temp_directory, state

    message, temp_directory, state = asyncio.run(scenario())

    assert message.answer_document.await_count == 7 
    assert message.answer.await_args.args == ( 
        BATCH_DELIVERY_COMPLETE.format(completed=7, total=7),
    )
    property_messages = [
        call.args[0]
        for call in message.answer.await_args_list 
        if call.args and call.args[0].startswith("━━━━━━━━━━")
    ]
    assert len(property_messages) == 7
    assert not temp_directory.exists()
    assert asyncio.run(state.get_state()) is None


def test_each_copy_properties_are_sent_before_its_document() -> None:
    async def scenario() -> list[str]:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        events: list[str] = []

        async def record_message(text: str, **kwargs: object) -> Message:
            del kwargs
            events.append(text)
            return message

        async def record_document(*, document: FSInputFile) -> None:
            events.append(f"document:{document.filename}")

        message.answer.side_effect = record_message 
        message.answer_document.side_effect = record_document 
        await workflow.run_batch(
            _callback(message, 1),
            state,
            1,
            BatchStates.processing,
        )
        return events

    events = asyncio.run(scenario())
    property_position = next(
        index for index, event in enumerate(events) if event.startswith("━━━━━━━━━━")
    )
    document_position = events.index("document:video_unique_001.mp4")
    assert property_position < document_position
    assert events[-1] == BATCH_DELIVERY_COMPLETE.format(completed=1, total=1)


def test_max_copies_rejection_keeps_pending_input() -> None:
    async def scenario() -> tuple[CallbackQuery, Path, BatchWorkflowService, Message, FSMContext]:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        temp_directory = Path((await state.get_data())["temp_directory"])
        callback = _callback(message, 50)
        await workflow.run_batch(
            callback,
            state,
            50,
            BatchStates.processing,
        )
        return callback, temp_directory, workflow, message, state

    callback, temp_directory, workflow, message, state = asyncio.run(scenario())
    assert callback.answer.await_args.args == ( 
        MAX_COPIES_EXCEEDED.format(max_copies=20),
    )
    assert callback.answer.await_args.kwargs["show_alert"] is True 
    assert temp_directory.exists()
    asyncio.run(workflow.cancel(message, state))
    assert not temp_directory.exists()


def test_active_user_cannot_prepare_another_file() -> None:
    async def scenario() -> tuple[Message, BatchWorkflowService, Message, FSMContext]:
        workflow = _workflow()
        first_state = _state()
        first_message = _message()
        await workflow.prepare(
            _bot(),
            first_message,
            _media(),
            first_state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        await first_state.set_state(BatchStates.waiting_for_custom_count)
        second_message = _message()
        prepared = await workflow.prepare(
            _bot(),
            second_message,
            _media(),
            _state(),
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        assert prepared is False
        return second_message, workflow, first_message, first_state

    second_message, workflow, first_message, first_state = asyncio.run(scenario())
    second_message.answer.assert_awaited_once_with(ACTIVE_PROCESS)
    asyncio.run(workflow.cancel(first_message, first_state))


def test_file_limit_is_checked_before_download() -> None:
    async def scenario() -> tuple[Message, Bot]:
        workflow = _workflow(max_file_size_mb=1)
        message = _message()
        bot = _bot()
        prepared = await workflow.prepare(
            bot,
            message,
            _media(file_size=1_048_577),
            _state(),
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        assert prepared is False
        return message, bot

    message, bot = asyncio.run(scenario())
    message.answer.assert_awaited_once_with(FILE_TOO_LARGE)
    bot.download.assert_not_awaited()


def test_cancel_removes_retained_input_and_clears_state() -> None:
    async def scenario() -> tuple[Message, Path, FSMContext]:
        workflow = _workflow()
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        temp_directory = Path((await state.get_data())["temp_directory"])
        await state.set_state(BatchStates.waiting_for_custom_count)
        await workflow.cancel(message, state)
        return message, temp_directory, state

    message, temp_directory, state = asyncio.run(scenario())
    assert not temp_directory.exists()
    assert asyncio.run(state.get_data()) == {}
    assert message.answer.await_args.args == (BATCH_CANCELLED,) 


def test_batch_error_is_hidden_and_temp_is_cleaned() -> None:
    async def scenario() -> tuple[Message, Path]:
        batch_processor = Mock(spec=BatchProcessor)
        batch_processor.generate_copies = AsyncMock(side_effect=OSError("disk full"))
        workflow = BatchWorkflowService(
            BotConfig(token="test"),
            cast(BatchProcessor, batch_processor),
        )
        state = _state()
        message = _message()
        await workflow.prepare(
            _bot(),
            message,
            _media(),
            state,
            copies_keyboard(),
            BatchStates.awaiting_copies,
        )
        temp_directory = Path((await state.get_data())["temp_directory"])
        await workflow.run_batch(
            _callback(message, 5),
            state,
            5,
            BatchStates.processing,
        )
        return message, temp_directory

    message, temp_directory = asyncio.run(scenario())
    assert message.answer.await_args.args == (PROCESSING_ERROR,) 
    assert not temp_directory.exists()
