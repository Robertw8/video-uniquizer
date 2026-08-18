# Video Uniquizer Engine

Backend-ядро для анализа и локальной обработки фото и видео. Engine
определяет тип файла, генерирует реалистичный профиль и применяет небольшие
изменения через FFmpeg, Pillow и ExifTool.

Архитектура не зависит от интерфейса. CLI — только один из потребителей
`MediaProcessor`; позднее поверх того же core можно добавить API, Telegram-бота
или worker без переноса бизнес-логики.

Поверх ядра доступен минимальный Telegram-бот на aiogram 3. Он использует
long polling, временные директории и тот же `MediaProcessor`; Telegram handlers
не содержат FFmpeg/Pillow logic.

## Требования

- Python 3.12+
- aiogram 3.x
- [FFmpeg и ffprobe](https://ffmpeg.org/) в `PATH`
- [ExifTool](https://exiftool.org/) в `PATH`

OpenCV не используется. FFmpeg анализирует и перекодирует видео, Pillow + NumPy
обрабатывают изображения, а ExifTool заменяет пользовательские metadata после
успешного сохранения результата.

## Установка

```bash
cd video_uniquizer
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Проверка внешних инструментов:

```bash
ffmpeg -version
ffprobe -version
exiftool -ver
```

## Запуск

```bash
# Только анализ и предпросмотр случайного профиля:
python cli.py input.mp4
python cli.py photo.jpg

# Реальная обработка видео:
python cli.py input.mp4 --output result.mp4

# Реальная обработка JPEG/PNG:
python cli.py photo.jpg --output result.jpg
python cli.py photo.png --output result.png --seed 42

# Явный device preset для любого поддерживаемого media type:
python cli.py input.mp4 --output result.mp4 --device "iPhone 14 Pro" --seed 42
python cli.py photo.jpg --output result.jpg --device "Galaxy S23" --seed 42

# Список доступных presets (input не нужен):
python cli.py --list-devices
```

Для воспроизводимого профиля и вывода выполняемых внешних команд:

```bash
python cli.py input.mp4 --output result.mp4 --seed 42 --verbose
```

## Telegram-бот

1. Создайте бота через BotFather и скопируйте token.
2. Создайте локальный `.env` из примера:

```bash
cp .env.example .env
```

3. Заполните обязательный token и при необходимости limits:

```dotenv
TELEGRAM_BOT_TOKEN=your-token
MAX_CONCURRENT_JOBS=2
MAX_FILE_SIZE_MB=
MAX_COPIES=20
MAX_BATCH_WORKERS=2
```

Пустой `MAX_FILE_SIZE_MB` отключает application-level limit; тогда действуют
только ограничения Telegram Bot API. Token читается только из environment или
локального `.env`, который исключён из Git.

4. Установите зависимости и убедитесь, что внешние media tools доступны:

```bash
python -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
exiftool -ver
```

5. Запустите long polling:

```bash
python -m bot.main
```

Бот принимает Telegram video, photo и media documents MP4/MOV/JPG/JPEG/PNG.
После загрузки он показывает быстрые варианты 1, 5, 10 и 20, не превышающие
`MAX_COPIES`, а также кнопку ручного ввода любого целого значения от 1 до
лимита. По умолчанию разрешено до 20 копий.

Каждая копия получает уникальный seed и обрабатывается отдельным
`MediaProcessor.with_seed()`. Общий batch `asyncio.Semaphore` допускает не
более `MAX_BATCH_WORKERS` одновременных FFmpeg/Pillow jobs. Каждый успешный
результат сразу отправляется отдельным document вместе с полным блоком
применённых параметров. Быстрые кнопки и ручной ввод используют один streaming
delivery flow; ZIP в Telegram workflow не создаётся.

FSM хранит только пути и небольшие параметры; сами файлы остаются на диске во
временной директории. Каждая copy удаляется после upload, а после завершения
удаляется вся директория. In-memory set не допускает параллельные batch jobs
одного пользователя. Ожидание быстрого выбора или ручного количества можно
отменить командой `/cancel`.

Видео поддерживает MP4/MOV и кодируется в H.264 (`libx264`) с аудио AAC. Фото
поддерживает JPEG/JPG/PNG. Формат результата определяется extension output;
существующий output не перезаписывается.

Видео проходит цепочку:

```text
micro zoom → color correction → unsharp → noise → setpts → fps → H.264
```

Скорость аудио синхронизируется фильтром `atempo`. Из FFmpeg-выхода удаляется
исходная metadata, затем ExifTool записывает модель устройства и дату профиля.

Изображение проходит цепочку:

```text
micro zoom → brightness → contrast → saturation → sharpness → RGB grain
```

JPEG сохраняется в RGB с quality из профиля. PNG сохраняет RGB/RGBA и alpha;
шум и color transformations применяются только к RGB. JPEG получает EXIF,
PNG — поддерживаемые XMP metadata.

## Архитектура

```text
video_uniquizer/
├── bot/        # aiogram FSM, batch services, messages, async adapters
├── core/       # orchestration, inspection, parameter generation, reports
├── devices/    # immutable Apple/Samsung capabilities and central registry
├── engines/    # isolated subprocess adapters for FFmpeg and ExifTool
├── models/     # immutable domain profiles
├── tests/      # unit tests independent of installed external tools
└── cli.py      # thin command-line adapter
```

- `models/profile.py` содержит отдельные immutable dataclass-профили для видео
  и фото без нерелевантных optional-полей.
- `devices/base.py` описывает immutable `DevicePreset`; `apple.py` и
  `samsung.py` содержат capabilities, а `registry.py` — единую точку
  регистрации и выбора моделей.
- `devices/validation.py` проверяет, что FPS и остальные значения профиля не
  выходят за capabilities выбранного устройства.
- `core/params.py` генерирует согласованные значения только из device preset.
  `random.Random`, текущее время и явную модель можно внедрять для полной
  воспроизводимости.
- `core/processor.py` анализирует файл, создаёт `ProcessingPlan` и делегирует в
  `VideoProcessor` или `ImageProcessor`.
- `core/image.py` декодирует JPEG/PNG, сохраняет результат и заменяет metadata.
- `core/image_filters.py` содержит чистые Pillow/NumPy transformations.
- `models/image.py` содержит immutable-модели `ImageInfo` и
  `ImageProcessingResult`.
- `core/video.py` получает разрешение, FPS, длительность, codec и bitrate и
  запускает H.264-кодирование.
- `core/video_filters.py` изолированно валидирует профиль и строит filter graph.
- `models/video.py` содержит immutable-модели `VideoInfo` и
  `VideoProcessingResult`.
- `engines/` отвечает только за безопасный запуск внешних программ через
  `subprocess` без shell.
- `core/metadata.py` предоставляет интерфейс metadata-сервиса поверх ExifTool.
- `bot/handlers/` распознаёт Telegram media и отвечает пользователю.
- `bot/services/processing.py` скачивает файл во временную директорию,
  ограничивает concurrency и вызывает существующий synchronous engine в
  worker thread.
- `bot/services/batch_processing.py` создаёт independently seeded copies,
  сохраняет partial successes и сообщает о готовых результатах callback-ом.
- `bot/services/batch_workflow.py` удерживает temporary input между upload и
  выбором количества, выполняет streaming delivery, обновляет progress и
  гарантирует cleanup FSM session.

`MediaProcessor.process()` принимает готовый plan или input path и выполняет
video/image processing без зависимости от CLI.

## Тесты

```bash
pytest -q
```

Только быстрые unit-тесты:

```bash
pytest -q -m "not integration"
```

Только реальные FFmpeg/ffprobe/ExifTool проверки:

```bash
pytest -q -m integration
```

Unit-тесты подменяют внешние subprocess-вызовы. Integration-тесты создают
настоящие MP4/MOV/JPEG/PNG fixtures, запускают FFmpeg/ExifTool и автоматически
пропускаются только при отсутствии конкретного обязательного бинарника.
