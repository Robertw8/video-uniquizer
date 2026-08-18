"""Telegram command handlers."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.messages import START_MESSAGE

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Explain the bot's single-file processing workflow."""
    await message.answer(START_MESSAGE)
