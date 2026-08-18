"""Aiogram routers for commands and media messages."""

from .batch import router as batch_router
from .media import router as media_router
from .start import router as start_router

__all__ = ["batch_router", "media_router", "start_router"]
