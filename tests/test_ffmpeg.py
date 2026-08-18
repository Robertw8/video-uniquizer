"""Tests for the FFmpeg and ffprobe subprocess adapter."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from engines.ffmpeg import (
    MediaToolExecutionError,
    MediaToolNotFoundError,
    probe_file,
    run_ffmpeg,
)


@patch("engines.ffmpeg.subprocess.run")
def test_run_ffmpeg_adds_executable(mock_run: Mock) -> None:
    completed = subprocess.CompletedProcess(["ffmpeg"], 0, "", "")
    mock_run.return_value = completed

    result = run_ffmpeg(["-version"])

    assert result is completed
    command = mock_run.call_args.args[0]
    assert command == ["ffmpeg", "-version"]
    assert mock_run.call_args.kwargs["check"] is True


@patch("engines.ffmpeg.subprocess.run", side_effect=FileNotFoundError)
def test_run_ffmpeg_reports_missing_executable(mock_run: Mock) -> None:
    with pytest.raises(MediaToolNotFoundError, match="not found"):
        run_ffmpeg(["-version"])
    mock_run.assert_called_once()


@patch("engines.ffmpeg.subprocess.run")
def test_probe_file_parses_json(mock_run: Mock, tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.touch()
    expected = {"streams": [{"codec_type": "video"}], "format": {}}
    mock_run.return_value = subprocess.CompletedProcess(
        ["ffprobe"], 0, json.dumps(expected), ""
    )

    assert probe_file(media) == expected
    assert mock_run.call_args.args[0][0] == "ffprobe"


@patch("engines.ffmpeg.subprocess.run")
def test_failed_command_includes_tool_output(mock_run: Mock) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=2,
        cmd=["ffmpeg"],
        stderr="invalid input",
    )

    with pytest.raises(MediaToolExecutionError, match="invalid input"):
        run_ffmpeg(["-i", "broken.mp4"])
