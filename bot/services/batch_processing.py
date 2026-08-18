"""Batch orchestration over independently seeded MediaProcessor instances."""

import asyncio
import logging
import random
import time
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from core.processor import MediaProcessor

from .batch_report import format_batch_text_report
from .processing import AsyncLimiter, ProcessingResult

logger = logging.getLogger(__name__)

SeededProcessorFactory = Callable[[int], MediaProcessor]


class InvalidCopyCountError(ValueError):
    """Raised when a requested batch size is outside configured limits."""


class EmptyBatchError(RuntimeError):
    """Raised when an archive cannot be created because every copy failed."""


@dataclass(frozen=True, slots=True)
class BatchProgress:
    """Progress snapshot emitted after a copy attempt finishes."""

    total: int
    completed: int
    failed: int

    @property
    def processed(self) -> int:
        return self.completed + self.failed


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Result of independently processing several copies of one input file."""

    total: int
    completed: int
    failed: int
    output_files: tuple[Path, ...]
    results: list[ProcessingResult]
    processing_time: float
    seeds: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _CopyOutcome:
    index: int
    result: ProcessingResult | None


ProgressCallback = Callable[[BatchProgress], Awaitable[None]]
ResultCallback = Callable[[int, ProcessingResult], Awaitable[None]]


class BatchProcessor:
    """Generate unique copies with bounded global worker concurrency."""

    def __init__(
        self,
        max_copies: int = 20,
        max_workers: int = 2,
        processor_factory: SeededProcessorFactory = MediaProcessor.with_seed,
        rng: random.Random | None = None,
        limiter: AsyncLimiter | None = None,
    ) -> None:
        if max_copies < 1:
            raise ValueError("max_copies must be positive.")
        if max_workers < 1:
            raise ValueError("max_workers must be positive.")
        self._max_copies = max_copies
        self._processor_factory = processor_factory
        self._rng = rng or random.SystemRandom()
        self._limiter = limiter or asyncio.Semaphore(max_workers)

    async def generate_copies(
        self,
        input_path: str | Path,
        copies: int,
        output_dir: str | Path,
        *,
        output_prefix: str,
        progress_callback: ProgressCallback | None = None,
        result_callback: ResultCallback | None = None,
    ) -> BatchResult:
        """Process every copy with a unique seed and keep partial successes."""
        self._validate_copies(copies)
        source = Path(input_path)
        if not source.is_file():
            raise FileNotFoundError(f"Batch input does not exist: {source}")
        if not output_prefix or Path(output_prefix).name != output_prefix:
            raise ValueError("output_prefix must be a plain filename prefix.")

        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        seeds = self._generate_unique_seeds(copies)
        suffix = source.suffix.lower()
        started_at = time.perf_counter()
        tasks = [
            asyncio.create_task(
                self._generate_one(
                    source,
                    destination / f"{output_prefix}_{index:03d}{suffix}",
                    seed,
                    index,
                )
            )
            for index, seed in enumerate(seeds, start=1)
        ]

        outcomes: list[_CopyOutcome] = []
        completed = 0
        failed = 0
        for task in asyncio.as_completed(tasks):
            outcome = await task
            outcomes.append(outcome)
            if outcome.result is None:
                failed += 1
            else:
                completed += 1
                if result_callback is not None:
                    await result_callback(outcome.index, outcome.result)
            if progress_callback is not None:
                await progress_callback(
                    BatchProgress(
                        total=copies,
                        completed=completed,
                        failed=failed,
                    )
                )

        successful_results = [
            outcome.result
            for outcome in sorted(outcomes, key=lambda item: item.index)
            if outcome.result is not None
        ]
        successful = tuple(result.output_file for result in successful_results)
        return BatchResult(
            total=copies,
            completed=completed,
            failed=failed,
            output_files=successful,
            results=successful_results,
            processing_time=time.perf_counter() - started_at,
            seeds=seeds,
        )

    @staticmethod
    def create_archive(result: BatchResult, archive_path: str | Path) -> Path:
        """Pack successful outputs into one ZIP without source directory names."""
        if not result.output_files:
            raise EmptyBatchError("No successful files are available for the archive.")
        destination = Path(archive_path)
        with zipfile.ZipFile(destination, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for output_file in result.output_files:
                archive.write(output_file, arcname=output_file.name)
            archive.writestr(
                "processing_report.txt",
                format_batch_text_report(result),
            )
        return destination

    async def _generate_one(
        self,
        source: Path,
        output_file: Path,
        seed: int,
        index: int,
    ) -> _CopyOutcome:
        async with self._limiter:
            try:
                result = await asyncio.to_thread(
                    self._process_one_sync,
                    source,
                    output_file,
                    seed,
                )
                return _CopyOutcome(index=index, result=result)
            except Exception:
                logger.exception("Batch copy failed index=%s seed=%s", index, seed)
                return _CopyOutcome(index=index, result=None)

    def _process_one_sync(
        self,
        source: Path,
        output_file: Path,
        seed: int,
    ) -> ProcessingResult:
        processor = self._processor_factory(seed)
        plan = processor.build_plan(source)
        return processor.process(plan, output_file)

    def _generate_unique_seeds(self, copies: int) -> tuple[int, ...]:
        seeds: list[int] = []
        seen: set[int] = set()
        while len(seeds) < copies:
            seed = self._rng.randrange(0, 2**63)
            if seed not in seen:
                seen.add(seed)
                seeds.append(seed)
        return tuple(seeds)

    def _validate_copies(self, copies: int) -> None:
        if copies < 1:
            raise InvalidCopyCountError("Copy count must be positive.")
        if copies > self._max_copies:
            raise InvalidCopyCountError(
                f"Copy count {copies} exceeds configured maximum {self._max_copies}."
            )
