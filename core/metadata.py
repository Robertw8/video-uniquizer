"""Business-facing metadata service built on the ExifTool adapter."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from engines.exiftool import MetadataValue, clear_metadata, read_metadata, write_metadata


class MetadataService:
    """Expose metadata operations without leaking subprocess details to callers."""

    def read(self, path: str | Path) -> dict[str, Any]:
        """Read all metadata ExifTool can expose as JSON."""
        return read_metadata(path)

    def replace(
        self,
        path: str | Path,
        metadata: Mapping[str, MetadataValue],
    ) -> None:
        """Clear writable tags, then write the supplied metadata values."""
        clear_metadata(path)
        if metadata:
            write_metadata(path, metadata)
