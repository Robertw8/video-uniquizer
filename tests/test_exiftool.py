"""Tests for the ExifTool subprocess adapter."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from engines.exiftool import clear_metadata, read_metadata, write_metadata


@patch("engines.exiftool.subprocess.run")
def test_read_metadata_returns_first_object(mock_run: Mock, tmp_path: Path) -> None:
    media = tmp_path / "photo.jpg"
    media.touch()
    mock_run.return_value = subprocess.CompletedProcess(
        ["exiftool"], 0, '[{"EXIF:Model": "iPhone 14 Pro"}]', ""
    )

    assert read_metadata(media) == {"EXIF:Model": "iPhone 14 Pro"}


@patch("engines.exiftool.subprocess.run")
def test_clear_metadata_avoids_backup_file(mock_run: Mock, tmp_path: Path) -> None:
    media = tmp_path / "photo.jpg"
    media.touch()
    mock_run.return_value = subprocess.CompletedProcess(["exiftool"], 0, "", "")

    clear_metadata(media)

    assert mock_run.call_args.args[0] == [
        "exiftool",
        "-overwrite_original",
        "-all=",
        str(media),
    ]


@patch("engines.exiftool.subprocess.run")
def test_write_metadata_uses_separate_arguments(mock_run: Mock, tmp_path: Path) -> None:
    media = tmp_path / "photo.jpg"
    media.touch()
    mock_run.return_value = subprocess.CompletedProcess(["exiftool"], 0, "", "")

    write_metadata(media, {"Model": "iPhone 15 Pro", "ISO": 100})

    assert mock_run.call_args.args[0] == [
        "exiftool",
        "-overwrite_original",
        "-Model=iPhone 15 Pro",
        "-ISO=100",
        str(media),
    ]


def test_write_metadata_rejects_empty_mapping(tmp_path: Path) -> None:
    media = tmp_path / "photo.jpg"
    media.touch()
    with pytest.raises(ValueError, match="at least one"):
        write_metadata(media, {})


def test_write_metadata_rejects_invalid_tag_name(tmp_path: Path) -> None:
    media = tmp_path / "photo.jpg"
    media.touch()
    with pytest.raises(ValueError, match="Invalid metadata tag"):
        write_metadata(media, {"unsafe tag": "value"})
