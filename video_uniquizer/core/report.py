"""Human-readable reports for CLI and other text interfaces."""

from models.profile import ImageProcessingProfile, ProcessingProfile, VideoProcessingProfile

from .image import ImageProcessingResult
from .processor import MediaInfo, ProcessingPlan
from .video import VideoProcessingResult


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} GiB"


def format_media_info(media: MediaInfo) -> str:
    """Format normalized file details as a compact multiline report."""
    lines = [
        f"File: {media.path}",
        f"Type: {media.kind.value}",
        f"Size: {_format_size(media.size_bytes)}",
    ]
    labels = {
        "format": "Format",
        "codec": "Codec",
        "width": "Width",
        "height": "Height",
        "mode": "Color mode",
        "has_alpha": "Has alpha",
        "frames": "Frames",
        "duration_seconds": "Duration",
        "fps": "Source FPS",
        "audio_streams": "Audio streams",
        "bitrate": "Bitrate",
    }
    for key, value in media.properties.items():
        if value is not None:
            suffix = " s" if key == "duration_seconds" else ""
            lines.append(f"{labels.get(key, key)}: {value}{suffix}")
    return "\n".join(lines)


def format_profile(profile: ProcessingProfile) -> str:
    """Format a generated processing profile."""
    lines = [
        f"Device: {profile.device_model}",
        f"Date: {profile.creation_date:%Y-%m-%d %H:%M:%S}",
    ]
    if isinstance(profile, VideoProcessingProfile):
        lines.extend(
            (
                f"FPS: {profile.fps}",
                f"Speed: {profile.speed_multiplier:.3f}x",
                f"Zoom: {profile.zoom_percent:+d}%",
            )
        )
    elif isinstance(profile, ImageProcessingProfile):
        lines.extend(
            (
                f"Zoom: {profile.zoom_percent:+d}%",
                f"JPEG quality: {profile.jpeg_quality}",
            )
        )

    lines.extend(
        (
            f"Brightness: {profile.brightness}",
            f"Contrast: {profile.contrast}",
            f"Saturation: {profile.saturation}",
            f"Sharpness: {profile.sharpness}",
            f"Noise: {profile.noise_level}",
        )
    )
    if isinstance(profile, VideoProcessingProfile):
        lines.append(f"CRF: {profile.crf}")
    return "\n".join(lines)


def format_plan(plan: ProcessingPlan) -> str:
    """Format file analysis and future transform parameters together."""
    return (
        "File information\n"
        "----------------\n"
        f"{format_media_info(plan.media)}\n\n"
        "Generated processing profile\n"
        "----------------------------\n"
        f"{format_profile(plan.profile)}"
    )


def format_video_result(result: VideoProcessingResult) -> str:
    """Format a successful processing result for the CLI."""
    profile = result.profile
    return (
        "✅ Видео успешно обработано\n\n"
        f"📱 Device: {profile.device_model}\n"
        f"📅 Date: {profile.creation_date:%Y-%m-%d %H:%M:%S}\n"
        f"🎬 FPS: {profile.fps}\n"
        f"⚡ Speed: {profile.speed_multiplier:.3f}x\n"
        f"🔍 Zoom: {profile.zoom_percent:+d}%\n"
        "🎨 Color: "
        f"brightness={profile.brightness}, "
        f"contrast={profile.contrast}, "
        f"saturation={profile.saturation}\n"
        f"✨ Sharpness: {profile.sharpness}\n"
        f"📺 Noise: {profile.noise_level}\n"
        f"📊 CRF: {profile.crf}\n\n"
        f"Output:\n{result.output_file}"
    )


def format_image_result(result: ImageProcessingResult) -> str:
    """Format a successful image processing result for the CLI."""
    profile = result.profile
    quality = (
        f"🖼 JPEG Quality: {profile.jpeg_quality}\n"
        if result.output_format == "JPEG"
        else ""
    )
    return (
        "✅ Фото успешно обработано\n\n"
        f"📱 Device: {profile.device_model}\n"
        f"📅 Date: {profile.creation_date:%Y-%m-%d %H:%M:%S}\n"
        f"🔍 Zoom: {profile.zoom_percent:+d}%\n"
        f"☀️ Brightness: {profile.brightness}\n"
        f"🎨 Contrast: {profile.contrast}\n"
        f"🌈 Saturation: {profile.saturation}\n"
        f"✨ Sharpness: {profile.sharpness}\n"
        f"📺 Noise: {profile.noise_level}\n"
        f"{quality}\n"
        "🗑 Старые metadata удалены и новый профиль записан.\n\n"
        f"Output:\n{result.output_file}"
    )
