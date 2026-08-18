"""Long-polling entrypoint for the Telegram MVP."""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.config import ConfigError, load_config
from bot.handlers import batch_router, media_router, start_router
from bot.services.batch_processing import BatchProcessor
from bot.services.batch_workflow import BatchWorkflowService
from bot.services.processing import ProcessingService


async def run() -> None:
    """Create aiogram resources and poll until a shutdown signal arrives."""
    config = load_config()
    bot = Bot(token=config.token)
    dispatcher = Dispatcher()
    dispatcher.include_routers(start_router, batch_router, media_router)
    processing_service = ProcessingService(config)
    batch_processor = BatchProcessor(
        max_copies=config.max_copies,
        max_workers=config.max_batch_workers,
    )
    batch_workflow_service = BatchWorkflowService(config, batch_processor)
    try:
        await dispatcher.start_polling(
            bot,
            processing_service=processing_service,
            batch_workflow_service=batch_workflow_service,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await batch_workflow_service.close()
        await bot.session.close()


def main() -> None:
    """Run long polling with concise configuration and shutdown behavior."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Telegram bot stopped")


if __name__ == "__main__":
    main()
