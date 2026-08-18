"""Pure Pillow transformations used by the image processor."""

import math

import numpy as np
from PIL import Image, ImageEnhance

from models.profile import ImageProcessingProfile


def validate_image_profile(profile: ImageProcessingProfile) -> None:
    """Reject values unsupported by the Pillow processing pipeline."""
    ranges = (
        ("zoom", profile.zoom_percent, 0, 10),
        ("brightness", profile.brightness, 0, 2),
        ("contrast", profile.contrast, 0, 2),
        ("saturation", profile.saturation, 0, 3),
        ("sharpness", profile.sharpness, -1, 4),
        ("noise", profile.noise_level, 0, 100),
        ("JPEG quality", profile.jpeg_quality, 1, 100),
    )
    for name, value, minimum, maximum in ranges:
        if not minimum <= value <= maximum:
            raise ValueError(
                f"Image {name} must be between {minimum} and {maximum}; got {value}."
            )


def apply_micro_zoom(image: Image.Image, zoom_percent: int) -> Image.Image:
    """Resize and center-crop an image back to its exact original dimensions."""
    if zoom_percent < 0 or zoom_percent > 10:
        raise ValueError("Image zoom must be between 0 and 10 percent.")
    if zoom_percent == 0:
        return image.copy()

    width, height = image.size
    factor = 1 + zoom_percent / 100
    resized_width = max(width, math.ceil(width * factor))
    resized_height = max(height, math.ceil(height * factor))
    resized = image.resize(
        (resized_width, resized_height),
        resample=Image.Resampling.LANCZOS,
    )
    left = (resized_width - width) // 2
    top = (resized_height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def apply_color_adjustments(
    image: Image.Image,
    profile: ImageProcessingProfile,
) -> Image.Image:
    """Apply Pillow multiplier semantics while preserving an alpha channel."""
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(profile.brightness)
    rgb = ImageEnhance.Contrast(rgb).enhance(profile.contrast)
    rgb = ImageEnhance.Color(rgb).enhance(profile.saturation)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.0 + profile.sharpness)
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def add_noise(
    image: Image.Image,
    noise_level: int,
    rng: np.random.Generator,
) -> Image.Image:
    """Add weak Gaussian RGB grain and leave alpha samples unchanged."""
    if noise_level < 0:
        raise ValueError("Image noise level must not be negative.")
    if noise_level == 0:
        return image.copy()

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb_values = np.asarray(image.convert("RGB"), dtype=np.float32)
    grain = rng.normal(0.0, float(noise_level), size=rgb_values.shape)
    noisy_values = np.clip(rgb_values + grain, 0, 255).astype(np.uint8)
    noisy = Image.fromarray(noisy_values)
    if alpha is not None:
        noisy.putalpha(alpha)
    return noisy


def process_image_pixels(
    image: Image.Image,
    profile: ImageProcessingProfile,
    rng: np.random.Generator,
) -> Image.Image:
    """Apply geometry, color adjustments, sharpness, and grain in order."""
    validate_image_profile(profile)
    zoomed = apply_micro_zoom(image, profile.zoom_percent)
    adjusted = apply_color_adjustments(zoomed, profile)
    return add_noise(adjusted, profile.noise_level, rng)
