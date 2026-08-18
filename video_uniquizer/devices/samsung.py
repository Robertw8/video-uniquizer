"""Samsung Galaxy processing presets."""

from .base import DevicePreset

STANDARD_FPS = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)


def _galaxy(
    model: str,
    *,
    jpeg_quality_range: tuple[int, int],
    sharpness_range: tuple[float, float],
) -> DevicePreset:
    return DevicePreset(
        manufacturer="Samsung",
        model=model,
        platform="Android",
        family="Galaxy S",
        allowed_fps=STANDARD_FPS,
        preferred_fps=(30.0, 60.0),
        video_codec="h264",
        pixel_format="yuv420p",
        crf_range=(22, 25),
        speed_range=(0.985, 1.025),
        zoom_range=(0, 2),
        brightness_range=(-0.025, 0.025),
        contrast_range=(0.97, 1.04),
        saturation_range=(0.96, 1.04),
        sharpness_range=sharpness_range,
        noise_levels=(1, 2),
        jpeg_quality_range=jpeg_quality_range,
        image_zoom_range=(0, 2),
        image_brightness_range=(0.97, 1.03),
        image_contrast_range=(0.97, 1.04),
        image_saturation_range=(0.96, 1.04),
        image_sharpness_range=sharpness_range,
        image_noise_levels=(1, 2),
        make="Samsung",
        metadata_family="QuickTime/EXIF",
    )


SAMSUNG_PRESETS: tuple[DevicePreset, ...] = (
    _galaxy(
        "Galaxy S22",
        jpeg_quality_range=(90, 95),
        sharpness_range=(0.30, 0.52),
    ),
    _galaxy(
        "Galaxy S23",
        jpeg_quality_range=(90, 96),
        sharpness_range=(0.31, 0.54),
    ),
    _galaxy(
        "Galaxy S24",
        jpeg_quality_range=(91, 97),
        sharpness_range=(0.32, 0.55),
    ),
)
