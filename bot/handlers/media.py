"""Telegram media recognition handlers with no processing internals."""

from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import Document, Message, PhotoSize, Video

from bot.messages import UNSUPPORTED_FILE, UNSUPPORTED_MESSAGE
from bot.services.processing import IncomingMedia, ProcessingService, TelegramMediaKind

VIDEO_EXTENSIONS = frozenset({".mp4", ".mov"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})

router = Router(name="media")


def media_from_video(video: Video) -> IncomingMedia:
    """Normalize a Telegram video, defaulting to its native MP4 container."""
    filename = video.file_name
    suffix = Path(filename).suffix.lower() if filename else ""
    extension = suffix if suffix in VIDEO_EXTENSIONS else ".mp4"
    return IncomingMedia(
        file_id=video.file_id,
        file_unique_id=video.file_unique_id,
        kind=TelegramMediaKind.VIDEO,
        extension=extension,
        file_size=video.file_size,
        original_filename=filename,
    )


def media_from_photo(photo: PhotoSize) -> IncomingMedia:
    """Normalize Telegram's largest selected compressed photo variant."""
    return IncomingMedia(
        file_id=photo.file_id,
        file_unique_id=photo.file_unique_id,
        kind=TelegramMediaKind.IMAGE,
        extension=".jpg",
        file_size=photo.file_size,
    )


def media_from_document(document: Document) -> IncomingMedia | None:
    """Normalize a supported image/video document or return None."""
    if not document.file_name:
        return None
    extension = Path(document.file_name).suffix.lower()
    if extension in VIDEO_EXTENSIONS:
        kind = TelegramMediaKind.VIDEO
    elif extension in IMAGE_EXTENSIONS:
        kind = TelegramMediaKind.IMAGE
    else:
        return None
    return IncomingMedia(
        file_id=document.file_id,
        file_unique_id=document.file_unique_id,
        kind=kind,
        extension=extension,
        file_size=document.file_size,
        original_filename=document.file_name,
    )


@router.message(F.video)
async def handle_video(
    message: Message,
    bot: Bot,
    processing_service: ProcessingService,
) -> None:
    """Process a Telegram-native video."""
    if message.video is None:
        return
    await processing_service.process(bot, message, media_from_video(message.video))


@router.message(F.photo)
async def handle_photo(
    message: Message,
    bot: Bot,
    processing_service: ProcessingService,
) -> None:
    """Process the largest available Telegram photo size."""
    if not message.photo:
        return
    photo = max(
        message.photo,
        key=lambda item: (item.width * item.height, item.file_size or 0),
    )
    await processing_service.process(bot, message, media_from_photo(photo))


@router.message(F.document)
async def handle_document(
    message: Message,
    bot: Bot,
    processing_service: ProcessingService,
) -> None:
    """Process supported media documents and reject other extensions."""
    if message.document is None:
        return
    media = media_from_document(message.document)
    if media is None:
        await message.answer(UNSUPPORTED_FILE)
        return
    await processing_service.process(bot, message, media)


@router.message()
async def handle_unsupported_message(message: Message) -> None:
    """Keep non-media messages harmless and provide a short hint."""
    await message.answer(UNSUPPORTED_MESSAGE)
