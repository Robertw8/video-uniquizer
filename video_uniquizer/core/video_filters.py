"""Pure FFmpeg video filter graph generation."""

from models.profile import VideoProcessingProfile


def _validate_profile(profile: VideoProcessingProfile) -> None:
    ranges = (
        ("zoom", profile.zoom_percent, 0, 10),
        ("speed multiplier", profile.speed_multiplier, 0.5, 2.0),
        ("FPS", profile.fps, 1, 240),
        ("brightness", profile.brightness, -1, 1),
        ("contrast", profile.contrast, 0, 2),
        ("saturation", profile.saturation, 0, 3),
        ("sharpness", profile.sharpness, -1.5, 1.5),
        ("noise", profile.noise_level, 0, 100),
        ("CRF", profile.crf, 0, 51),
    )
    for name, value, minimum, maximum in ranges:
        if not minimum <= value <= maximum:
            raise ValueError(
                f"Video {name} must be between {minimum} and {maximum}; got {value}."
            )


def build_filter_complex(profile: VideoProcessingProfile) -> str:
    """Build the ordered FFmpeg video filter graph for a profile."""
    _validate_profile(profile)

    filters: list[str] = []
    if profile.zoom_percent:
        zoom_factor = 1 + profile.zoom_percent / 100
        factor = f"{zoom_factor:.6f}"
        filters.extend(
            (
                f"scale=ceil(iw*{factor}/2)*2:ceil(ih*{factor}/2)*2",
                f"crop=trunc(iw/{factor}/2)*2:trunc(ih/{factor}/2)*2",
                "setsar=1",
            )
        )

    filters.extend(
        (
            "eq="
            f"brightness={profile.brightness:.3f}:"
            f"contrast={profile.contrast:.3f}:"
            f"saturation={profile.saturation:.3f}",
            f"unsharp=5:5:{profile.sharpness:.2f}:5:5:0.0",
            f"noise=alls={profile.noise_level}:allf=t+u",
            f"setpts=PTS/{profile.speed_multiplier:.3f}",
            f"fps={profile.fps:g}",
        )
    )
    return f"[0:v:0]{','.join(filters)}[video]"
