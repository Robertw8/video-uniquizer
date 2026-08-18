"""Tests for independently seeded batch processing and ZIP creation."""

import asyncio
import random
import zipfile
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from bot.services.batch_processing import (
    BatchProcessor,
    EmptyBatchError,
    InvalidCopyCountError,
)
from core.processor import MediaProcessor
from models.image import ImageProcessingResult
from models.profile import ImageProcessingProfile, VideoProcessingProfile
from models.video import VideoProcessingResult


class FakeProcessor:
    def __init__(self, seed: int, failing_seeds: set[int]) -> None:
        self.seed = seed
        self.failing_seeds = failing_seeds

    def build_plan(self, source: Path) -> tuple[Path, int]:
        return source, self.seed

    def process(
        self,
        plan: object,
        output_path: Path,
    ) -> VideoProcessingResult | ImageProcessingResult:
        if self.seed in self.failing_seeds:
            raise RuntimeError(f"copy failed for seed {self.seed}")
        output_path.write_text(f"processed with seed {self.seed}", encoding="utf-8")
        source = cast(tuple[Path, int], plan)[0]
        if source.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            return ImageProcessingResult(
                input_file=source,
                output_file=output_path,
                profile=ImageProcessingProfile(
                    device_model=f"Image Device {self.seed}",
                    creation_date=datetime(2026, 8, 1, 12, 0),
                    brightness=1.01,
                    contrast=0.99,
                    saturation=1.02,
                    sharpness=0.4,
                    noise_level=2,
                    jpeg_quality=92,
                    zoom_percent=1,
                ),
                processing_time=0.1,
                width=320,
                height=240,
                output_format="JPEG",
            )
        return VideoProcessingResult(
            input_file=source,
            output_file=output_path,
            profile=VideoProcessingProfile(
                device_model=f"Video Device {self.seed}",
                creation_date=datetime(2026, 8, 1, 12, 0),
                brightness=0.01,
                contrast=0.99,
                saturation=1.02,
                sharpness=0.4,
                noise_level=2,
                fps=29.97,
                speed_multiplier=1.01,
                zoom_percent=1,
                crf=24,
            ),
            processing_time=0.1,
            ffmpeg_command=("ffmpeg",),
        )


def _factory(
    recorded_seeds: list[int],
    failing_seeds: set[int] | None = None,
) -> object:
    failures = failing_seeds or set()

    def create(seed: int) -> MediaProcessor:
        recorded_seeds.append(seed)
        return cast(MediaProcessor, FakeProcessor(seed, failures))

    return create


def _rng(values: list[int]) -> random.Random:
    rng = Mock(spec=random.Random)
    rng.randrange.side_effect = values
    return cast(random.Random, rng)


def test_each_output_uses_a_distinct_seed_and_processor(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    recorded_seeds: list[int] = []
    processor = BatchProcessor(
        max_copies=20,
        max_workers=2,
        processor_factory=_factory(recorded_seeds), 
        rng=_rng([11, 22, 33, 44, 55]),
    )

    result = asyncio.run(
        processor.generate_copies(
            source,
            5,
            tmp_path / "outputs",
            output_prefix="video_unique",
        )
    )

    assert result.total == 5
    assert result.completed == 5
    assert result.failed == 0
    assert result.seeds == (11, 22, 33, 44, 55)
    assert sorted(recorded_seeds) == [11, 22, 33, 44, 55]
    assert [path.name for path in result.output_files] == [
        "video_unique_001.mp4",
        "video_unique_002.mp4",
        "video_unique_003.mp4",
        "video_unique_004.mp4",
        "video_unique_005.mp4",
    ]
    assert len(result.results) == 5
    assert [item.output_file for item in result.results] == list(result.output_files)
    assert len({path.read_text(encoding="utf-8") for path in result.output_files}) == 5


@pytest.mark.parametrize("copies", (0, -1, 21))
def test_invalid_and_over_limit_copy_counts(tmp_path: Path, copies: int) -> None:
    source = tmp_path / "input.jpg"
    source.write_bytes(b"input")
    processor = BatchProcessor(max_copies=20)

    with pytest.raises(InvalidCopyCountError):
        asyncio.run(
            processor.generate_copies(
                source,
                copies,
                tmp_path / "outputs",
                output_prefix="image_unique",
            )
        )


def test_duplicate_random_values_are_not_reused_as_seeds(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    source.write_bytes(b"input")
    recorded: list[int] = []
    processor = BatchProcessor(
        processor_factory=_factory(recorded), 
        rng=_rng([7, 7, 8]),
    )

    result = asyncio.run(
        processor.generate_copies(
            source,
            2,
            tmp_path / "outputs",
            output_prefix="image_unique",
        )
    )

    assert result.seeds == (7, 8)


def test_partial_failures_keep_successful_outputs(tmp_path: Path) -> None:
    source = tmp_path / "input.mov"
    source.write_bytes(b"input")
    recorded: list[int] = []
    progress: list[tuple[int, int, int]] = []
    processor = BatchProcessor(
        processor_factory=_factory(recorded, {22, 44}), 
        rng=_rng([11, 22, 33, 44, 55]),
    )

    async def record_progress(value: object) -> None:
        progress.append((value.completed, value.failed, value.total)) 

    result = asyncio.run(
        processor.generate_copies(
            source,
            5,
            tmp_path / "outputs",
            output_prefix="video_unique",
            progress_callback=record_progress,
        )
    )

    assert result.completed == 3
    assert result.failed == 2
    assert len(result.output_files) == 3
    assert len(progress) == 5
    assert progress[-1] == (3, 2, 5)


def test_successful_results_are_emitted_as_each_copy_completes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    emitted: list[tuple[int, Path]] = []
    processor = BatchProcessor(
        processor_factory=_factory([]), 
        rng=_rng([11, 22, 33]),
    )

    async def receive_result(index: int, result: object) -> None:
        emitted.append((index, result.output_file))

    result = asyncio.run(
        processor.generate_copies(
            source,
            3,
            tmp_path / "outputs",
            output_prefix="video_unique",
            result_callback=receive_result,
        )
    )

    assert len(emitted) == 3
    assert sorted(index for index, _ in emitted) == [1, 2, 3]
    assert {path for _, path in emitted} == set(result.output_files)


def test_archive_contains_only_flat_successful_files(tmp_path: Path) -> None:
    source = tmp_path / "input.jpg"
    source.write_bytes(b"input")
    recorded: list[int] = []
    processor = BatchProcessor(
        processor_factory=_factory(recorded, {2}), 
        rng=_rng([1, 2, 3]),
    )
    result = asyncio.run(
        processor.generate_copies(
            source,
            3,
            tmp_path / "outputs",
            output_prefix="image_unique",
        )
    )

    archive_path = processor.create_archive(result, tmp_path / "images_unique.zip")

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [
            "image_unique_001.jpg",
            "image_unique_003.jpg",
            "processing_report.txt",
        ]
        report = archive.read("processing_report.txt").decode("utf-8")
        assert "Копия #1" in report
        assert "Копия #2" in report
        assert report.count("🖼 JPEG Quality: 92") == 2


def test_empty_batch_cannot_create_archive(tmp_path: Path) -> None:
    source = tmp_path / "input.jpg"
    source.write_bytes(b"input")
    recorded: list[int] = []
    processor = BatchProcessor(
        processor_factory=_factory(recorded, {1}), 
        rng=_rng([1]),
    )
    result = asyncio.run(
        processor.generate_copies(
            source,
            1,
            tmp_path / "outputs",
            output_prefix="image_unique",
        )
    )

    with pytest.raises(EmptyBatchError):
        processor.create_archive(result, tmp_path / "empty.zip")


class RecordingLimiter:
    def __init__(self) -> None:
        self.entries = 0

    async def __aenter__(self) -> object:
        self.entries += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        return None


def test_each_copy_uses_batch_semaphore(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    limiter = RecordingLimiter()
    processor = BatchProcessor(
        processor_factory=_factory([]), 
        rng=_rng([1, 2, 3]),
        limiter=limiter,
    )

    asyncio.run(
        processor.generate_copies(
            source,
            3,
            tmp_path / "outputs",
            output_prefix="video_unique",
        )
    )

    assert limiter.entries == 3
