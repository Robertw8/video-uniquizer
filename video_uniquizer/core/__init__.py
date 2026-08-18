"""Public interfaces for the media processing core."""

from .image import ImageProcessingResult, ImageProcessor
from .processor import MediaKind, MediaProcessor, ProcessingPlan
from .video import VideoProcessingResult, VideoProcessor

__all__ = [
    "ImageProcessingResult",
    "ImageProcessor",
    "MediaKind",
    "MediaProcessor",
    "ProcessingPlan",
    "VideoProcessingResult",
    "VideoProcessor",
]
