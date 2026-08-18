"""Real batch regression over the existing image processing engine."""

import asyncio
import hashlib
import random
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from bot.messages import format_processing_properties
from bot.services.batch_processing import BatchProcessor

pytestmark = pytest.mark.integration


def test_real_batch_creates_distinct_images_and_valid_zip(
    generated_images: dict[str, Path],
    tmp_path: Path,
) -> None:
    processor = BatchProcessor(
        max_copies=3,
        max_workers=2,
        rng=random.Random(42),
    )

    result = asyncio.run(
        processor.generate_copies(
            generated_images["landscape"],
            3,
            tmp_path / "outputs",
            output_prefix="image_unique",
        )
    )

    assert result.completed == 3
    assert result.failed == 0
    assert len(set(result.seeds)) == 3
    digests = set()
    for output_file in result.output_files:
        with Image.open(output_file) as image:
            image.verify()
        digests.add(hashlib.sha256(output_file.read_bytes()).hexdigest())
    assert len(digests) == 3

    archive_path = processor.create_archive(result, tmp_path / "images_unique.zip")
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [
            "image_unique_001.jpg",
            "image_unique_002.jpg",
            "image_unique_003.jpg",
            "processing_report.txt",
        ]
        report = archive.read("processing_report.txt").decode("utf-8")
        assert report.count("Копия #") == 3
        for processing_result in result.results:
            assert format_processing_properties(processing_result) in report
