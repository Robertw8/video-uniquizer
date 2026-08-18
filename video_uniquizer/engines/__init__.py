"""Adapters for external media-processing executables."""

from .exiftool import clear_metadata, read_metadata, write_metadata
from .ffmpeg import probe_file, run_ffmpeg

__all__ = [
    "clear_metadata",
    "probe_file",
    "read_metadata",
    "run_ffmpeg",
    "write_metadata",
]
