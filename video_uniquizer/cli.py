"""Command-line interface for inspecting and processing local media."""

import argparse
import logging
from collections.abc import Sequence

from core.image import ImageInspectionError, ImageProcessingError
from core.processor import MediaProcessor, UnsupportedMediaError
from core.report import format_image_result, format_plan, format_video_result
from core.video import VideoProcessingError
from devices.registry import list_devices
from engines.exiftool import ExifToolError
from engines.ffmpeg import MediaToolError
from models.image import ImageProcessingResult


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Inspect or process JPEG, PNG, MP4, and MOV media."
    )
    parser.add_argument("input", nargs="?", help="Path to the input image or video")
    parser.add_argument("--output", help="Process media and write it to this path")
    parser.add_argument("--seed", type=int, help="Generate a reproducible profile")
    parser.add_argument(
        "--device",
        help='Use an explicit smartphone preset, for example "iPhone 14 Pro"',
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List supported smartphone presets and exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable command logging",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line application and return a process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.list_devices:
        current_manufacturer: str | None = None
        for preset in list_devices():
            if preset.manufacturer != current_manufacturer:
                if current_manufacturer is not None:
                    print()
                current_manufacturer = preset.manufacturer
                print(f"{current_manufacturer}:")
            print(f"  - {preset.model}")
        return 0
    if args.input is None:
        build_parser().error("the following arguments are required: input")

    try:
        if args.device is not None:
            processor = MediaProcessor.for_device(args.device, seed=args.seed)
        elif args.seed is not None:
            processor = MediaProcessor.with_seed(args.seed)
        else:
            processor = MediaProcessor()
        plan = processor.build_plan(args.input)
        if args.output:
            result = processor.process(plan, args.output)
            if isinstance(result, ImageProcessingResult):
                print(format_image_result(result))
            else:
                print(format_video_result(result))
        else:
            print(format_plan(plan))
    except (
        UnsupportedMediaError,
        MediaToolError,
        ExifToolError,
        ImageInspectionError,
        ImageProcessingError,
        VideoProcessingError,
        OSError,
        NotImplementedError,
        ValueError,
    ) as exc:
        logging.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
