"""Aiogram FSM handlers for selecting and generating unique copy batches."""

from typing import cast

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.messages import (
    BATCH_CANNOT_CANCEL,
    CUSTOM_COPY_COUNT_INTEGER,
    CUSTOM_COPY_COUNT_NOT_NUMBER,
    CUSTOM_COPY_COUNT_PROMPT,
    CUSTOM_COPY_COUNT_TOO_HIGH,
    CUSTOM_COPY_COUNT_ZERO,
    UNSUPPORTED_FILE,
)
from bot.services.batch_workflow import BatchWorkflowService
from bot.services.processing import IncomingMedia

from .media import media_from_document, media_from_photo, media_from_video

COPY_CHOICES = (1, 5, 10, 20)
COPY_CALLBACK_PREFIX = "batch:copies:"
CUSTOM_COUNT_CALLBACK = "batch:custom-count"

router = Router(name="batch")


class BatchStates(StatesGroup):
    """States retained between Telegram upload and copies callback."""

    awaiting_copies = State()
    waiting_for_custom_count = State()
    processing = State()


def copies_keyboard(max_copies: int = 20) -> InlineKeyboardMarkup:
    """Build quick choices constrained by the configured maximum."""
    quick_choices = [copies for copies in COPY_CHOICES if copies <= max_copies]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(copies),
                    callback_data=f"{COPY_CALLBACK_PREFIX}{copies}",
                )
                for copies in quick_choices
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Ввести количество",
                    callback_data=CUSTOM_COUNT_CALLBACK,
                )
            ],
        ]
    )


async def _prepare(
    message: Message,
    bot: Bot,
    state: FSMContext,
    workflow: BatchWorkflowService,
    media: IncomingMedia,
) -> None:
    await workflow.prepare(
        bot,
        message,
        media,
        state,
        copies_keyboard(workflow.max_copies),
        BatchStates.awaiting_copies,
    )


@router.message(Command("cancel"))
async def handle_batch_cancel(
    message: Message,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Cancel a retained input before or during batch selection."""
    if await state.get_state() == BatchStates.processing.state:
        await message.answer(BATCH_CANNOT_CANCEL)
        return
    await batch_workflow_service.cancel(message, state)


@router.message(F.video)
async def handle_batch_video(
    message: Message,
    bot: Bot,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Retain a Telegram-native video and prompt for copy count."""
    if message.video is None:
        return
    await _prepare(
        message,
        bot,
        state,
        batch_workflow_service,
        media_from_video(message.video),
    )


@router.message(F.photo)
async def handle_batch_photo(
    message: Message,
    bot: Bot,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Retain the largest Telegram photo and prompt for copy count."""
    if not message.photo:
        return
    photo = max(
        message.photo,
        key=lambda item: (item.width * item.height, item.file_size or 0),
    )
    await _prepare(
        message,
        bot,
        state,
        batch_workflow_service,
        media_from_photo(photo),
    )


@router.message(F.document)
async def handle_batch_document(
    message: Message,
    bot: Bot,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Retain a supported media document or reject its extension."""
    if message.document is None:
        return
    media = media_from_document(message.document)
    if media is None:
        await message.answer(UNSUPPORTED_FILE)
        return
    await _prepare(message, bot, state, batch_workflow_service, media)


@router.callback_query(
    BatchStates.awaiting_copies,
    F.data.startswith(COPY_CALLBACK_PREFIX),
)
async def handle_copies_callback(
    callback: CallbackQuery,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Validate a configured quick choice and start streaming delivery."""
    raw_value = (callback.data or "").removeprefix(COPY_CALLBACK_PREFIX)
    try:
        copies = int(raw_value)
    except ValueError:
        await callback.answer("Некорректное количество копий.", show_alert=True)
        return
    if copies not in COPY_CHOICES or copies > batch_workflow_service.max_copies:
        await callback.answer("Некорректное количество копий.", show_alert=True)
        return
    await batch_workflow_service.run_batch(
        callback,
        state,
        copies,
        BatchStates.processing,
    )


@router.callback_query(
    BatchStates.awaiting_copies,
    F.data == CUSTOM_COUNT_CALLBACK,
)
async def handle_custom_count_callback(
    callback: CallbackQuery,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Switch a pending batch to free-form copy-count input."""
    await callback.answer()
    if callback.message is None:
        return
    await state.set_state(BatchStates.waiting_for_custom_count)
    message = cast(Message, callback.message)
    await message.answer(
        CUSTOM_COPY_COUNT_PROMPT.format(
            max_copies=batch_workflow_service.max_copies,
        )
    )


@router.message(BatchStates.awaiting_copies)
@router.message(BatchStates.waiting_for_custom_count)
async def handle_custom_count_message(
    message: Message,
    state: FSMContext,
    batch_workflow_service: BatchWorkflowService,
) -> None:
    """Validate a manually entered count and start the shared batch flow."""
    max_copies = batch_workflow_service.max_copies
    if await state.get_state() != BatchStates.waiting_for_custom_count.state:
        await state.set_state(BatchStates.waiting_for_custom_count)
    raw_value = (message.text or "").strip()
    if not raw_value:
        await message.answer(CUSTOM_COPY_COUNT_NOT_NUMBER)
        return
    if not raw_value.isdigit():
        error = (
            CUSTOM_COPY_COUNT_INTEGER.format(max_copies=max_copies)
            if _looks_numeric(raw_value)
            else CUSTOM_COPY_COUNT_NOT_NUMBER
        )
        await message.answer(error)
        return

    copies = int(raw_value)
    if copies == 0:
        await message.answer(
            CUSTOM_COPY_COUNT_ZERO.format(max_copies=max_copies)
        )
        return
    if copies > max_copies:
        await message.answer(
            CUSTOM_COPY_COUNT_TOO_HIGH.format(max_copies=max_copies)
        )
        return
    await state.set_state(BatchStates.processing)
    await batch_workflow_service.run_batch_from_message(
        message,
        state,
        copies,
        BatchStates.processing,
    )


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
