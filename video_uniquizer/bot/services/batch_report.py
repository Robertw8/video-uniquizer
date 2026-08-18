"""Full batch reports for Telegram messages and ZIP archives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.messages import format_processing_properties

from .processing import ProcessingResult

if TYPE_CHECKING:
    from .batch_processing import BatchResult

TELEGRAM_MESSAGE_LIMIT = 4096
COPY_SEPARATOR = "━━━━━━━━━━"


def format_batch_text_report(result: BatchResult) -> str:
    """Build the complete UTF-8 report stored in every successful batch ZIP."""
    return format_batch_telegram_report(result) + "\n"


def format_batch_telegram_report(result: BatchResult) -> str:
    """Build one unsplit report containing every successful copy."""
    sections = [_format_header(result)]
    sections.extend(
        format_batch_copy_report(index, processing_result)
        for index, processing_result in enumerate(result.results, start=1)
    )
    return "\n\n".join(sections)


def format_batch_telegram_messages(
    result: BatchResult,
    *,
    message_limit: int = TELEGRAM_MESSAGE_LIMIT,
) -> list[str]:
    """Split a full report without breaking a copy block when it can fit."""
    if message_limit < 1:
        raise ValueError("message_limit must be positive.")

    header = _format_header(result)
    blocks = [
        format_batch_copy_report(index, processing_result)
        for index, processing_result in enumerate(result.results, start=1)
    ]
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= message_limit:
            current = candidate
            continue
        messages.extend(_split_if_needed(current, message_limit))
        if len(block) <= message_limit:
            current = block
        else:
            block_parts = _split_if_needed(block, message_limit)
            messages.extend(block_parts[:-1])
            current = block_parts[-1]
    messages.extend(_split_if_needed(current, message_limit))
    return messages


def _format_header(result: BatchResult) -> str:
    if result.failed:
        status = (
            f"⚠️ Создано {result.completed} из {result.total} "
            "уникальных копий."
        )
        return f"{status}\n\n📋 Применённые параметры:"
    return (
        "✅ Готово!\n\n"
        f"Создано: {result.completed}/{result.total} уникальных копий\n\n"
        "📋 Применённые параметры:"
    )


def format_batch_copy_report(index: int, result: ProcessingResult) -> str:
    """Format one complete copy block for streaming Telegram delivery."""
    return (
        f"{COPY_SEPARATOR}\n"
        f"Копия #{index}\n"
        f"{COPY_SEPARATOR}\n\n"
        f"{format_processing_properties(result)}"
    )


def _split_if_needed(text: str, limit: int) -> list[str]:
    """Split an oversized section by whole lines as a defensive fallback."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                parts.append(current.rstrip("\n"))
                current = ""
            parts.extend(
                line[start : start + limit].rstrip("\n")
                for start in range(0, len(line), limit)
            )
            continue
        if current and len(current) + len(line) > limit:
            parts.append(current.rstrip("\n"))
            current = line
        else:
            current += line
    if current:
        parts.append(current.rstrip("\n"))
    return parts
