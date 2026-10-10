"""Regressions for multidisc detection and literal directory ignore patterns."""

import os
from pathlib import Path

import pytest
from beetsplug import path_utils


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CD1", True),
        ("cd 02", True),
        ("Album CD1", True),
        ("Album-CD1", True),
        ("Album___CD1", True),
        ("Album-_-CD1", True),
        ("Disc 1 [Live]", True),
        ("Disk2", True),
        ("UDCD 2-591", False),
        ("ABCD1", False),
        ("AlbumCD1", False),
        ("CD Collection 1", False),
        (
            (
                "[1972] Something_Anything_ {1994,US,Mobile Fidelity,"
                "UDCD 2-591[FLAC 16-44]"
            ),
            False,
        ),
    ],
)
def test_is_multidisc(name: str, expected: bool) -> None:
    """CD markers inside words must not identify albums as disc folders."""
    assert path_utils.is_multidisc(Path(name)) is expected


@pytest.mark.parametrize(
    ("disc_name", "sibling_name"),
    [
        ("CD1 [Live]", "CD1 L"),
        pytest.param(
            "CD1*",
            "CD1bonus",
            marks=pytest.mark.skipif(
                os.name == "nt", reason="Invalid Windows filename"
            ),
        ),
        pytest.param(
            "CD1?",
            "CD1x",
            marks=pytest.mark.skipif(
                os.name == "nt", reason="Invalid Windows filename"
            ),
        ),
    ],
)
def test_multidisc_ignore_patterns_are_literal(
    tmp_path: Path, disc_name: str, sibling_name: str
) -> None:
    """Parent discovery skips exact disc names, not glob-shaped siblings."""
    disc = tmp_path / disc_name
    sibling = tmp_path / sibling_name
    disc.mkdir()
    ignore = path_utils.get_multidisc_ignore_paths(tmp_path)
    sibling.mkdir()
    (disc / "disc.txt").touch()
    (sibling / "sibling.txt").touch()
    (tmp_path / "ignored.txt").touch()

    assert path_utils.discover_artifacts(
        tmp_path, ignore=[*ignore, "ignored.*"], beets_file_types={}
    ) == [sibling / "sibling.txt"]
