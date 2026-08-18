"""Tests for quick choices, custom copy counts, and batch FSM handlers."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, Video

from bot.handlers.batch import (
    CUSTOM_COUNT_CALLBACK,
    BatchStates,
    copies_keyboard,
    handle_batch_cancel,
    handle_batch_video,
    handle_copies_callback,
    handle_custom_count_callback,
    handle_custom_count_message,
)
from bot.messages import (
    BATCH_CANNOT_CANCEL,
    CUSTOM_COPY_COUNT_INTEGER,
    CUSTOM_COPY_COUNT_NOT_NUMBER,
    CUSTOM_COPY_COUNT_PROMPT,
    CUSTOM_COPY_COUNT_TOO_HIGH,
    CUSTOM_COPY_COUNT_ZERO,
)
from bot.services.batch_workflow import BatchWorkflowService


def _state() -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=100, user_id=100),
    )


def _message(
    video: Video | None = None,
    *,
    text: str | None = None,
) -> Message:
    return cast(
        Message,
        SimpleNamespace(
            video=video,
            text=text,
            from_user=SimpleNamespace(id=100),
            chat=SimpleNamespace(id=100),
            answer=AsyncMock(),
        ),
    )


def _workflow(max_copies: int = 20) -> BatchWorkflowService:
    return cast(
        BatchWorkflowService,
        SimpleNamespace(
            max_copies=max_copies,
            prepare=AsyncMock(return_value=True),
            run_batch=AsyncMock(),
            run_batch_from_message=AsyncMock(),
            cancel=AsyncMock(),
        ),
    )


def _custom_callback(message: Message) -> CallbackQuery:
    return cast(
        CallbackQuery,
        SimpleNamespace(
            data=CUSTOM_COUNT_CALLBACK,
            message=message,
            answer=AsyncMock(),
        ),
    )


def test_copy_keyboard_contains_quick_choices_and_custom_button() -> None:
    keyboard = copies_keyboard(20)

    assert [button.text for button in keyboard.inline_keyboard[0]] == [
        "1",
        "5",
        "10",
        "20",
    ]
    assert [button.callback_data for button in keyboard.inline_keyboard[0]] == [
        "batch:copies:1",
        "batch:copies:5",
        "batch:copies:10",
        "batch:copies:20",
    ]
    assert keyboard.inline_keyboard[1][0].text == "✏️ Ввести количество"
    assert keyboard.inline_keyboard[1][0].callback_data == CUSTOM_COUNT_CALLBACK


def test_quick_buttons_above_max_copies_are_hidden() -> None:
    keyboard = copies_keyboard(10)

    assert [button.text for button in keyboard.inline_keyboard[0]] == ["1", "5", "10"]
    assert keyboard.inline_keyboard[1][0].text == "✏️ Ввести количество"


def test_video_handler_uses_configured_copy_limit_for_keyboard() -> None:
    video = Video(
        file_id="video-id",
        file_unique_id="video-unique",
        width=320,
        height=180,
        duration=2,
        file_size=100,
    )
    message = _message(video)
    workflow = _workflow(max_copies=10)
    state = _state()
    bot = cast(Bot, SimpleNamespace())

    asyncio.run(handle_batch_video(message, bot, state, workflow))

    arguments = workflow.prepare.await_args.args  
    keyboard = arguments[4]
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["1", "5", "10"]
    assert arguments[5] is BatchStates.awaiting_copies


def test_quick_callback_passes_selected_count_to_shared_workflow() -> None:
    async def scenario() -> tuple[BatchWorkflowService, FSMContext]:
        workflow = _workflow()
        state = _state()
        callback = cast(
            CallbackQuery,
            SimpleNamespace(data="batch:copies:10", answer=AsyncMock()),
        )
        await handle_copies_callback(callback, state, workflow)
        return workflow, state

    workflow, state = asyncio.run(scenario())

    workflow.run_batch.assert_awaited_once()  
    arguments = workflow.run_batch.await_args.args  
    assert arguments[1] is state
    assert arguments[2] == 10
    assert arguments[3] is BatchStates.processing


def test_quick_callback_above_configured_limit_is_rejected() -> None:
    async def scenario() -> tuple[CallbackQuery, BatchWorkflowService]:
        workflow = _workflow(max_copies=10)
        callback = cast(
            CallbackQuery,
            SimpleNamespace(data="batch:copies:20", answer=AsyncMock()),
        )
        await handle_copies_callback(callback, _state(), workflow)
        return callback, workflow

    callback, workflow = asyncio.run(scenario())

    callback.answer.assert_awaited_once_with(  
        "Некорректное количество копий.",
        show_alert=True,
    )
    workflow.run_batch.assert_not_awaited()  


def test_custom_callback_enters_waiting_state_and_prompts_user() -> None:
    async def scenario() -> tuple[CallbackQuery, Message, FSMContext]:
        state = _state()
        await state.set_state(BatchStates.awaiting_copies)
        message = _message()
        callback = _custom_callback(message)
        await handle_custom_count_callback(callback, state, _workflow())
        return callback, message, state

    callback, message, state = asyncio.run(scenario())

    callback.answer.assert_awaited_once_with()  
    assert asyncio.run(state.get_state()) == BatchStates.waiting_for_custom_count.state
    message.answer.assert_awaited_once_with(  
        CUSTOM_COPY_COUNT_PROMPT.format(max_copies=20)
    )


@pytest.mark.parametrize("value", ("1", "7", "13", "20"))
def test_valid_custom_count_starts_shared_streaming_workflow(value: str) -> None:
    async def scenario() -> tuple[BatchWorkflowService, Message, FSMContext]:
        workflow = _workflow()
        state = _state()
        await state.set_state(BatchStates.waiting_for_custom_count)
        message = _message(text=value)
        await handle_custom_count_message(message, state, workflow)
        return workflow, message, state

    workflow, message, state = asyncio.run(scenario())

    workflow.run_batch_from_message.assert_awaited_once_with(  
        message,
        state,
        int(value),
        BatchStates.processing,
    )
    assert asyncio.run(state.get_state()) == BatchStates.processing.state


def test_number_can_be_entered_directly_from_initial_copy_choice_state() -> None:
    async def scenario() -> tuple[BatchWorkflowService, Message, FSMContext]:
        workflow = _workflow()
        state = _state()
        await state.set_state(BatchStates.awaiting_copies)
        message = _message(text="7")
        await handle_custom_count_message(message, state, workflow)
        return workflow, message, state

    workflow, message, state = asyncio.run(scenario())

    workflow.run_batch_from_message.assert_awaited_once_with(  
        message,
        state,
        7,
        BatchStates.processing,
    )
    assert asyncio.run(state.get_state()) == BatchStates.processing.state


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("21", CUSTOM_COPY_COUNT_TOO_HIGH.format(max_copies=20)),
        ("0", CUSTOM_COPY_COUNT_ZERO.format(max_copies=20)),
        ("-5", CUSTOM_COPY_COUNT_INTEGER.format(max_copies=20)),
        ("5.5", CUSTOM_COPY_COUNT_INTEGER.format(max_copies=20)),
        ("abc", CUSTOM_COPY_COUNT_NOT_NUMBER),
        ("", CUSTOM_COPY_COUNT_NOT_NUMBER),
    ),
)
def test_invalid_custom_count_keeps_state_for_retry(
    value: str,
    expected: str,
) -> None:
    async def scenario() -> tuple[BatchWorkflowService, Message, FSMContext]:
        workflow = _workflow()
        state = _state()
        await state.set_state(BatchStates.waiting_for_custom_count)
        message = _message(text=value)
        await handle_custom_count_message(message, state, workflow)
        return workflow, message, state

    workflow, message, state = asyncio.run(scenario())

    message.answer.assert_awaited_once_with(expected)  
    workflow.run_batch_from_message.assert_not_awaited()  
    assert asyncio.run(state.get_state()) == BatchStates.waiting_for_custom_count.state


def test_invalid_then_valid_custom_count_reuses_pending_workflow() -> None:
    async def scenario() -> tuple[BatchWorkflowService, FSMContext, Message]:
        workflow = _workflow()
        state = _state()
        await state.set_state(BatchStates.waiting_for_custom_count)
        invalid = _message(text="100")
        await handle_custom_count_message(invalid, state, workflow)
        assert await state.get_state() == BatchStates.waiting_for_custom_count.state
        valid = _message(text="13")
        await handle_custom_count_message(valid, state, workflow)
        return workflow, state, valid

    workflow, state, valid = asyncio.run(scenario())

    workflow.run_batch_from_message.assert_awaited_once_with(  
        valid,
        state,
        13,
        BatchStates.processing,
    )


def test_cancel_clears_custom_count_workflow() -> None:
    async def scenario() -> tuple[Message, BatchWorkflowService]:
        workflow = _workflow()
        state = _state()
        await state.set_state(BatchStates.waiting_for_custom_count)
        message = _message()
        await handle_batch_cancel(message, state, workflow)
        return message, workflow

    message, workflow = asyncio.run(scenario())

    workflow.cancel.assert_awaited_once()  
    message.answer.assert_not_awaited()  


def test_cancel_during_processing_does_not_remove_files() -> None:
    async def scenario() -> tuple[Message, BatchWorkflowService]:
        workflow = _workflow()
        state = _state()
        await state.set_state(BatchStates.processing)
        message = _message()
        await handle_batch_cancel(message, state, workflow)
        return message, workflow

    message, workflow = asyncio.run(scenario())

    message.answer.assert_awaited_once_with(BATCH_CANNOT_CANCEL)  
    workflow.cancel.assert_not_awaited()  
