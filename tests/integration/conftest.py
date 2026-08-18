"""Real media fixtures generated with the installed FFmpeg binary."""

import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engines.exiftool import write_metadata
from engines.ffmpeg import run_ffmpeg

REQUIRED_BINARIES = ("ffmpeg", "ffprobe", "exiftool")


@pytest.fixture(scope="session")
def require_media_tools() -> None:
    """Skip E2E tests only when a required executable is genuinely absent."""
    missing = [name for name in REQUIRED_BINARIES if shutil.which(name) is None]
    if missing:
        pytest.skip(f"Missing required media binaries: {', '.join(missing)}")


@pytest.fixture(scope="session")
def require_exiftool() -> None:
    """Skip image metadata E2E tests only when ExifTool is unavailable."""
    if shutil.which("exiftool") is None:
        pytest.skip("Missing required media binary: exiftool")


def _generate_video(
    destination: Path,
    *,
    size: str,
    rate: str,
    duration: float,
    audio: bool,
) -> None:
    command = [
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate={rate}",
    ]
    if audio:
        command.extend(
            (
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:sample_rate=48000",
            )
        )
    command.extend(
        (
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
        )
    )
    if audio:
        command.extend(("-c:a", "aac", "-shortest"))
    else:
        command.append("-an")
    command.extend(("-movflags", "+faststart", str(destination)))
    run_ffmpeg(command)


@pytest.fixture(scope="session")
def generated_videos(
    require_media_tools: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Path]:
    """Create all required real input formats once per integration session."""
    del require_media_tools
    root = tmp_path_factory.mktemp("real_media")
    videos = {
        "vertical": root / "vertical.mp4",
        "horizontal": root / "horizontal.mp4",
        "no_audio": root / "no_audio.mp4",
        "mov": root / "sample.mov",
        "very_short": root / "very_short.mp4",
    }
    _generate_video(
        videos["vertical"],
        size="180x320",
        rate="30",
        duration=2.4,
        audio=True,
    )
    _generate_video(
        videos["horizontal"],
        size="320x180",
        rate="30000/1001",
        duration=2.4,
        audio=True,
    )
    _generate_video(
        videos["no_audio"],
        size="240x160",
        rate="30",
        duration=2.0,
        audio=False,
    )
    _generate_video(
        videos["mov"],
        size="256x144",
        rate="30",
        duration=2.2,
        audio=True,
    )
    _generate_video(
        videos["very_short"],
        size="160x120",
        rate="30",
        duration=0.15,
        audio=True,
    )

    write_metadata(
        videos["vertical"],
        {
            "Title": "Legacy Title",
            "Comment": "Legacy Comment",
            "Artist": "Legacy Artist",
            "Keys:CreationDate": "2020:01:02 03:04:05+01:00",
            "UserData:Model": "Legacy Camera",
        },
    )

    videos["spaces"] = root / "input with spaces.mp4"
    videos["unicode"] = root / "видео тест.mp4"
    shutil.copyfile(videos["horizontal"], videos["spaces"])
    shutil.copyfile(videos["horizontal"], videos["unicode"])
    return videos


def _image_pattern(width: int, height: int, *, alpha: bool = False) -> Image.Image:
    y, x = np.indices((height, width))
    rgb = np.stack((x * 5, y * 7, (x + y) * 3), axis=2)
    rgb = np.mod(rgb, 256).astype(np.uint8)
    if not alpha:
        return Image.fromarray(rgb)
    alpha_values = np.linspace(0, 255, width, dtype=np.uint8)
    alpha_channel = np.broadcast_to(alpha_values, (height, width))
    return Image.fromarray(np.dstack((rgb, alpha_channel)))


@pytest.fixture(scope="session")
def generated_images(
    require_exiftool: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Path]:
    """Create real JPEG/PNG inputs, including alpha and legacy metadata."""
    del require_exiftool
    root = tmp_path_factory.mktemp("real_images")
    images = {
        "portrait": root / "portrait.jpg",
        "landscape": root / "landscape.jpg",
        "rgb_png": root / "rgb.png",
        "rgba_png": root / "rgba.png",
        "odd": root / "odd_301x199.jpg",
        "legacy": root / "legacy.jpg",
    }
    _image_pattern(180, 320).save(images["portrait"], quality=95)
    _image_pattern(320, 180).save(images["landscape"], quality=95)
    _image_pattern(240, 160).save(images["rgb_png"])
    _image_pattern(240, 160, alpha=True).save(images["rgba_png"])
    _image_pattern(301, 199).save(images["odd"], quality=95)
    shutil.copyfile(images["portrait"], images["legacy"])
    write_metadata(
        images["legacy"],
        {
            "EXIF:Artist": "Legacy Artist",
            "EXIF:UserComment": "Legacy Comment",
            "EXIF:Make": "Legacy Make",
            "EXIF:Model": "Legacy Model",
            "EXIF:DateTimeOriginal": "2020:01:02 03:04:05",
        },
    )
    return images
