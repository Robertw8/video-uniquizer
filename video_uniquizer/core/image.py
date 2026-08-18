"""Image inspection and Pillow-based processing."""

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from core.image_filters import process_image_pixels
from core.metadata import MetadataService
from devices.registry import get_device
from engines.exiftool import ExifToolError, MetadataValue
from models.image import ImageInfo, ImageProcessingResult
from models.profile import ImageProcessingProfile

SUPPORTED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
OUTPUT_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}


class ImageInspectionError(RuntimeError):
    """Raised when an image cannot be decoded."""


class ImageProcessingError(RuntimeError):
    """Raised when an image cannot be processed."""


class UnsupportedImageFormatError(ImageProcessingError):
    """Raised when an input or output image extension is unsupported."""


def _has_alpha(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def get_image_info(path: str | Path) -> ImageInfo:
    """Decode an image and return normalized technical details."""
    image_path = Path(path)
    try:
        with Image.open(image_path) as source:
            source.load()
            width, height = source.size
            return ImageInfo(
                width=width,
                height=height,
                format=source.format or image_path.suffix.lstrip(".").upper(),
                mode=source.mode,
                has_alpha=_has_alpha(source),
            )
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageInspectionError(
            f"Cannot inspect image '{image_path}': {exc}"
        ) from exc


def inspect_image(path: str | Path) -> dict[str, Any]:
    """Return image details in the MediaProcessor-compatible mapping format."""
    info = get_image_info(path)
    return {
        "format": info.format,
        "width": info.width,
        "height": info.height,
        "mode": info.mode,
        "has_alpha": info.has_alpha,
    }


class ImageProcessor:
    """Process JPEG and PNG images using Pillow and ExifTool abstractions."""

    def __init__(
        self,
        metadata_service: MetadataService | None = None,
        noise_rng: np.random.Generator | None = None,
    ) -> None:
        self._metadata_service = (
            metadata_service if metadata_service is not None else MetadataService()
        )
        self._noise_rng = noise_rng or np.random.default_rng()

    def get_info(self, path: str | Path) -> ImageInfo:
        """Return decoded image information."""
        return get_image_info(path)

    def process(
        self,
        input_path: str | Path,
        output_path: str | Path,
        profile: ImageProcessingProfile,
    ) -> ImageProcessingResult:
        """Apply a profile, save the image, and replace user metadata."""
        source_path = Path(input_path).expanduser().resolve()
        destination = Path(output_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Input image does not exist: {source_path}")
        self._validate_extension(source_path, "Input")
        self._validate_extension(destination, "Output")
        if source_path == destination:
            raise ImageProcessingError("Input and output paths must be different.")
        if destination.exists():
            raise FileExistsError(f"Output file already exists: {destination}")
        if not destination.parent.is_dir():
            raise FileNotFoundError(
                f"Output directory does not exist: {destination.parent}"
            )

        output_format = OUTPUT_FORMATS[destination.suffix.lower()]
        started_at = time.perf_counter()
        try:
            with Image.open(source_path) as source:
                source.load()
                width, height = source.size
                working = self._normalize_mode(source, output_format)
            processed = process_image_pixels(working, profile, self._noise_rng)
            self._save(processed, destination, output_format, profile)
            self._metadata_service.replace(
                destination,
                self._metadata_for(output_format, profile),
            )
        except (UnidentifiedImageError, ExifToolError, OSError) as exc:
            raise ImageProcessingError(
                f"Image processing failed for '{source_path}': {exc}"
            ) from exc

        return ImageProcessingResult(
            input_file=source_path,
            output_file=destination,
            profile=profile,
            processing_time=time.perf_counter() - started_at,
            width=width,
            height=height,
            output_format=output_format,
        )

    @staticmethod
    def _normalize_mode(source: Image.Image, output_format: str) -> Image.Image:
        if output_format == "JPEG":
            return source.convert("RGB")
        return source.convert("RGBA" if _has_alpha(source) else "RGB")

    @staticmethod
    def _save(
        image: Image.Image,
        destination: Path,
        output_format: str,
        profile: ImageProcessingProfile,
    ) -> None:
        if output_format == "JPEG":
            image.convert("RGB").save(
                destination,
                format="JPEG",
                quality=profile.jpeg_quality,
                optimize=True,
                progressive=False,
            )
        else:
            image.save(destination, format="PNG", optimize=True)

    @staticmethod
    def _metadata_for(
        output_format: str,
        profile: ImageProcessingProfile,
    ) -> Mapping[str, MetadataValue]:
        preset = get_device(profile.device_model)
        timestamp = profile.creation_date.strftime("%Y:%m:%d %H:%M:%S")
        if output_format == "JPEG":
            return {
                "EXIF:Make": preset.make,
                "EXIF:Model": preset.model,
                "EXIF:DateTimeOriginal": timestamp,
                "EXIF:CreateDate": timestamp,
                "EXIF:ModifyDate": timestamp,
            }
        return {
            "XMP-tiff:Make": preset.make,
            "XMP-tiff:Model": preset.model,
            "XMP-exif:DateTimeOriginal": timestamp,
            "XMP-xmp:CreateDate": timestamp,
            "XMP-xmp:ModifyDate": timestamp,
        }

    @staticmethod
    def _validate_extension(path: Path, label: str) -> None:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS))
            raise UnsupportedImageFormatError(
                f"{label} image extension '{suffix or '<none>'}' is unsupported. "
                f"Supported extensions: {supported}."
            )
