"""Tests for single-disc album folders whose names merely look like disc folders.

A folder such as `[1972] Album {UDCD 2-591[FLAC 16-44]` matches beets' disc pattern
(`CD` followed by a digit). Without a sibling disc folder it must not be treated as a
disc, otherwise its parent (e.g. the artist folder) is scanned as the album root and
its extras are exported a second time under `$subpath`.
"""

import importlib
from pathlib import Path

import pytest

from beets import plugins

from tests.pytest_beets_plugin import BeetsPluginFixture
from tests.pytest_beets_plugin._item_model import MediaMeta
from tests.pytest_beets_plugin.plugin_lifecycle import (
    _activate_plugins,
    _deactivate_plugins,
)

ALBUM_NAME = "[1972] Something {1994,US,Mobile Fidelity,UDCD 2-591[FLAC 16-44]"
ARTIFACTS = ["album.cue", "album.log", "album.1.cue", "album.1.log"]


@pytest.fixture
def env(beets_plugin_env: BeetsPluginFixture) -> BeetsPluginFixture:
    """Creates `Artist/<disc-like album>/` with tracks tagged as disc 1 of 2."""
    album_path: Path = beets_plugin_env.import_dir / "Tag Artist" / ALBUM_NAME
    album_path.mkdir(parents=True)

    for artifact in ARTIFACTS:
        beets_plugin_env.create_file(album_path / artifact)

    for track in (1, 2):
        beets_plugin_env.create_medium(
            album_path / f"track_{track}.mp3",
            MediaMeta(
                title=f"Tag Title {track}",
                album=ALBUM_NAME,
                track=track,
                disc=1,
                disctotal=2,
            ),
        )

    beets_plugin_env.setup_import_session(autotag=False)
    beets_plugin_env.config["filetote"]["extensions"] = [".cue", ".log"]
    beets_plugin_env.config["filetote"]["paths"] = {
        "filetote:default": "$albumpath/$subpath$old_filename",
    }
    return beets_plugin_env


def _assert_exported_once(root: Path) -> None:
    """Every extra exists once, at the album root, with no nested album folder."""
    album_dir = root / "Tag Artist" / ALBUM_NAME

    for artifact in ARTIFACTS:
        assert (album_dir / artifact).is_file()
        assert len(list(root.rglob(artifact))) == 1

    assert not (album_dir / ALBUM_NAME).exists()


def test_import_does_not_nest_extras(env: BeetsPluginFixture) -> None:
    """Import copies root extras only to the album root."""
    env.run_cli_command("import")

    _assert_exported_once(env.lib_dir)


def test_convert_does_not_nest_extras(env: BeetsPluginFixture) -> None:
    """Convert exports root extras only to the destination album root."""
    env.run_cli_command("import")
    destination = env.temp_dir / "converted"
    env.config["convert"]["dest"] = str(destination)

    _activate_plugins()
    try:
        convert = importlib.import_module("beetsplug.convert").ConvertPlugin()
        plugins._instances.append(convert)  # ruff: ignore[private-member-access]
        plugins.send("pluginload")
        convert.config["format"] = "mp3"
        convert.config["write_metadata"] = False
        convert.config["paths"] = {"default": "$artist/$album/$title"}
        command = convert.commands()[0]
        opts, args = command.parser.parse_args(["--yes"])
        command.func(env.lib, opts, args)
        plugins.send("cli_exit", lib=env.lib)
    finally:
        _deactivate_plugins()

    _assert_exported_once(destination)
