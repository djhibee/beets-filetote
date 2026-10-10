"""Tests for exporting extra files with the real beets convert plugin."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest

from beets import plugins, util

from tests.pytest_beets_plugin.plugin_lifecycle import (
    _activate_plugins,
    _deactivate_plugins,
)

if TYPE_CHECKING:
    from tests.pytest_beets_plugin import BeetsEnvFactory, BeetsPluginFixture


def _convert(
    env: BeetsPluginFixture, *, pretend: bool = False, keep_new: bool = False
) -> None:
    """Export using convert's real worker without requiring a transcoder."""
    _activate_plugins()
    try:
        plugins.send("pluginload")
        convert = importlib.import_module("beetsplug.convert").ConvertPlugin()
        convert.config["format"] = "mp3"
        convert.config["pretend"] = pretend
        convert.config["write_metadata"] = False
        convert.config["threads"] = 2
        convert.config["keep_new"] = keep_new
        items = list(env.lib.items())
        convert._parallel_convert(items, keep_new=keep_new)  # ruff: ignore[private-member-access]
        plugins.send("cli_exit", lib=env.lib)
    finally:
        _deactivate_plugins()


@pytest.mark.parametrize(
    ("link", "hardlink"),
    [
        (False, False),
        pytest.param(True, False, marks=pytest.mark.needs_symlink),
        pytest.param(True, True, marks=pytest.mark.needs_hardlink),
    ],
)
@pytest.mark.parametrize("keep_new", [False, True])
def test_convert_exports_artifacts(
    beets_flat_env: BeetsEnvFactory, link: bool, hardlink: bool, keep_new: bool
) -> None:
    """Conversion exports preserve source extras and honor link precedence."""
    env = beets_flat_env()
    env.config["filetote"]["extensions"] = ".*"
    env.config["filetote"]["pairing"]["enabled"] = True
    env.run_cli_command("import")
    destination = env.temp_dir / "converted"
    env.config["convert"]["dest"] = str(destination)
    env.config["convert"]["link"] = link
    env.config["convert"]["hardlink"] = hardlink
    # A stale import session must not cause exports to move library extras.
    env.config["import"]["move"] = True
    env.config["filetote"]["pairing"]["enabled"] = True
    env.config["filetote"]["exclude"]["filenames"] = "artifact.nfo"

    _convert(env, keep_new=keep_new)
    _convert(env, keep_new=keep_new)

    source = env.lib_dir / "Tag Artist" / "Tag Album"
    target = destination / "Tag Artist" / "Tag Album"
    assert (source / "artifact.file").is_file()
    assert (target / "artifact.file").is_file()
    assert not (target / "artifact.nfo").exists()
    assert not (target / "artifact.1.file").exists()
    for item in env.lib.items():
        assert (target / f"{item.filepath.stem}.lrc").is_file()
    if hardlink:
        assert (source / "artifact.file").stat().st_ino == (
            target / "artifact.file"
        ).stat().st_ino
    elif link:
        assert (target / "artifact.file").is_symlink()
        assert (target / "artifact.file").resolve() == source / "artifact.file"
    else:
        assert not (target / "artifact.file").is_symlink()
        assert (source / "artifact.file").stat().st_ino != (
            target / "artifact.file"
        ).stat().st_ino


def test_convert_pretend_does_not_export_extras(
    beets_flat_env: BeetsEnvFactory,
) -> None:
    """Dry-run conversions leave the export directory untouched."""
    env = beets_flat_env()
    env.config["filetote"]["extensions"] = ".*"
    env.run_cli_command("import")
    destination = env.temp_dir / "converted"
    env.config["convert"]["dest"] = str(destination)
    _convert(env, pretend=True)
    assert not destination.exists()


def test_convert_uses_output_name_and_subpath(
    beets_flat_env: BeetsEnvFactory,
) -> None:
    """Paired extras follow converted names; configured subpaths are preserved."""
    env = beets_flat_env(pair_subfolders=True)
    env.config["filetote"]["extensions"] = ".*"
    env.config["filetote"]["pairing"]["enabled"] = True
    env.config["filetote"]["paths"]["filetote:default"] = (
        "$albumpath/$subpath/$old_filename"
    )
    env.config["filetote"]["paths"]["filetote-pairing:default"] = (
        "$albumpath/$subpath/$medianame_new"
    )
    env.run_cli_command("import")
    destination = env.temp_dir / "converted" / "renamed.mp3"
    env.config["convert"]["hardlink"] = False
    env.config["convert"]["link"] = False

    _activate_plugins()
    try:
        plugins.send("pluginload")
        item = next(iter(env.lib.items()))
        destination.parent.mkdir()
        destination.touch()
        plugins.send(
            "after_convert",
            item=item,
            dest=util.bytestring_path(destination),
            keepnew=False,
        )
        plugins.send("cli_exit", lib=env.lib)
    finally:
        _deactivate_plugins()

    assert (destination.parent / "lyrics/lyric-subfolder/renamed.lrc").is_file()
    assert (destination.parent / "artifact.file").is_file()


def test_convert_without_inclusion_rules(beets_flat_env: BeetsEnvFactory) -> None:
    """Conversion keeps Filetote's opt-in behavior for extra files."""
    env = beets_flat_env()
    env.config["filetote"]["extensions"] = ".*"
    env.run_cli_command("import")
    env.config["filetote"]["extensions"] = ""
    destination = env.temp_dir / "converted"
    env.config["convert"]["dest"] = str(destination)
    _convert(env)
    assert list(destination.rglob("*.mp3"))
    assert not list(destination.rglob("*.file"))
    assert not list(destination.rglob("*.lrc"))


def test_convert_multidisc_extras(beets_nested_env: BeetsEnvFactory) -> None:
    """Multi-disc exports include parent and disc extras without moving sources."""
    env = beets_nested_env(parent_artifacts=["summary.txt"])
    env.config["filetote"]["extensions"] = ".*"
    env.config["paths"]["default"] = "$artist/$album/CD$disc/$title"
    env.lib.path_formats = [
        ("default", "$artist/$album/CD$disc/$title"),
    ]
    env.run_cli_command("import")
    destination = env.temp_dir / "converted"
    env.config["convert"]["dest"] = str(destination)
    _convert(env)
    assert list(destination.rglob("summary.txt"))
    assert list(destination.rglob("artifact.file"))
    assert list(env.lib_dir.rglob("summary.txt"))
