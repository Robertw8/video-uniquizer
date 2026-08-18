"""User-facing Telegram messages and result formatting."""

from models.image import ImageProcessingResult
from models.video import VideoProcessingResult

START_MESSAGE = """👋 Привет!

Отправь мне видео или фотографию, и я обработаю файл.

Поддерживаются:

🎬 Видео:
• MP4
• MOV

🖼 Фото:
• JPG / JPEG
• PNG

Просто отправь файл — остальное бот сделает автоматически."""

FILE_RECEIVED = "⏳ Файл получен. Начинаю обработку..."
PROCESSING_STARTED = "⚙️ Обрабатываю файл..."
ACTIVE_JOB = (
    "⏳ Ваш предыдущий файл ещё обрабатывается.\n\n"
    "Дождитесь завершения и отправьте следующий."
)
UNSUPPORTED_FILE = """❌ Этот формат пока не поддерживается.

Поддерживаются:
🎬 MP4, MOV
🖼 JPG, JPEG, PNG"""
UNSUPPORTED_MESSAGE = (
    "Отправьте видео MP4/MOV или фотографию JPG/JPEG/PNG для обработки."
)
PROCESSING_ERROR = """❌ Не удалось обработать файл.

Попробуйте другой файл или повторите попытку."""
FILE_TOO_LARGE = """❌ Файл превышает допустимый размер.

Попробуйте отправить файл меньшего размера."""
CHOOSE_COPIES = "📦 Файл сохранён.\n\nСколько уникальных копий создать?"
CUSTOM_COPY_COUNT_PROMPT = (
    "🔢 Введите количество уникальных копий.\n\n"
    "Допустимо: от 1 до {max_copies}."
)
CUSTOM_COPY_COUNT_TOO_HIGH = (
    "❌ Максимально доступно {max_copies} копий.\n\n"
    "Введите число от 1 до {max_copies}."
)
CUSTOM_COPY_COUNT_ZERO = (
    "❌ Количество копий должно быть от 1 до {max_copies}."
)
CUSTOM_COPY_COUNT_INTEGER = "❌ Введите целое число от 1 до {max_copies}."
CUSTOM_COPY_COUNT_NOT_NUMBER = (
    "❌ Введите количество числом.\n\n"
    "Например: 7"
)
ACTIVE_PROCESS = (
    "⏳ Ваш предыдущий процесс ещё выполняется.\n\n"
    "Дождитесь завершения и отправьте следующий файл."
)
BATCH_STARTED = "⏳ Создаю {copies} уникальных копий..."
BATCH_PROGRESS = "⚙️ Прогресс:\n\n{completed}/{total} готово"
BATCH_COMPLETE = "✅ Создано {completed} уникальных копий."
BATCH_PARTIAL = "⚠️ Создано {completed} из {total} копий."
BATCH_DELIVERY_COMPLETE = (
    "✅ Готово!\n\n"
    "Создано и отправлено: {completed}/{total} уникальных копий."
)
BATCH_DELIVERY_PARTIAL = (
    "⚠️ Обработка завершена.\n\n"
    "Успешно создано и отправлено: {completed}/{total}\n"
    "Ошибок: {failed}"
)
BATCH_CANCELLED = "✅ Создание копий отменено."
BATCH_CANNOT_CANCEL = "⏳ Обработка уже выполняется и не может быть отменена."
MAX_COPIES_EXCEEDED = "❌ Максимально доступно {max_copies} копий."
METADATA_UPDATED = "🗑 Старые метаданные удалены и новый профиль записан."


def format_video_properties(result: VideoProcessingResult) -> str:
    """Format reusable Telegram properties for one processed video."""
    profile = result.profile
    return (
        f"📱 Устройство: {profile.device_model}\n"
        f"📅 Дата съёмки: {profile.creation_date:%Y-%m-%d %H:%M:%S}\n"
        f"🎬 FPS: {profile.fps:g}\n"
        f"⚡ Скорость: {profile.speed_multiplier:.3f}x\n"
        f"🔍 Микро-зум: {profile.zoom_percent:+d}%\n"
        "🎨 Цветокоррекция: "
        f"C:{profile.contrast} | B:{profile.brightness} | "
        f"S:{profile.saturation}\n"
        f"✨ Резкость: {profile.sharpness:+g}\n"
        f"📺 Шум: {profile.noise_level}\n"
        f"📊 CRF: {profile.crf}\n\n"
        f"{METADATA_UPDATED}"
    )


def format_image_properties(result: ImageProcessingResult) -> str:
    """Format reusable Telegram properties for one processed image."""
    profile = result.profile
    quality = (
        f"🖼 JPEG Quality: {profile.jpeg_quality}\n"
        if result.output_format == "JPEG"
        else ""
    )
    return (
        f"📱 Устройство: {profile.device_model}\n"
        f"📅 Дата съёмки: {profile.creation_date:%Y-%m-%d %H:%M:%S}\n"
        f"🔍 Микро-зум: {profile.zoom_percent:+d}%\n"
        f"☀️ Яркость: {profile.brightness}\n"
        f"🎨 Контраст: {profile.contrast}\n"
        f"🌈 Насыщенность: {profile.saturation}\n"
        f"✨ Резкость: {profile.sharpness:+g}\n"
        f"📺 Шум: {profile.noise_level}\n"
        f"{quality}\n"
        f"{METADATA_UPDATED}"
    )


def format_processing_properties(
    result: VideoProcessingResult | ImageProcessingResult,
) -> str:
    """Format properties shared by single-file and batch Telegram reports."""
    if isinstance(result, VideoProcessingResult):
        return format_video_properties(result)
    return format_image_properties(result)


def format_processing_result(
    result: VideoProcessingResult | ImageProcessingResult,
) -> str:
    """Format an engine result without exposing local paths or commands."""
    if isinstance(result, VideoProcessingResult):
        return (
            "✅ Видео успешно обработано!\n\n"
            "📋 Применённые параметры:\n\n"
            f"{format_video_properties(result)}"
        )
    return (
        "✅ Фото успешно обработано!\n\n"
        "📋 Применённые параметры:\n\n"
        f"{format_image_properties(result)}"
    )
