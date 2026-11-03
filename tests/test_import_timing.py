"""Tests for processing extras before downstream import listeners."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from beets import plugins
from beets.library import Item
from beets.plugins import BeetsPlugin

from tests.pytest_beets_plugin import MediaSetup
from tests.pytest_beets_plugin.plugin_lifecycle import _activate_plugins

if TYPE_CHECKING:
    from beets.library import Album, Library

    from tests.pytest_beets_plugin import BeetsEnvFactory


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("move", [False, True])
@pytest.mark.parametrize("singletons", [False, True])
@pytest.mark.parametrize("threaded", [False, True])
def test_import_listener_sees_extras(
    beets_flat_env: BeetsEnvFactory,
    enabled: bool,
    move: bool,
    singletons: bool,
    threaded: bool,
) -> None:
    """Import listeners see extras only in opt-in mode, without exit duplicates."""
    env = beets_flat_env(
        media_files=[MediaSetup(count=3)],
        move=move,
        singletons=singletons,
        threaded=threaded,
    )
    env.config["filetote"]["process_on_import"] = enabled
    env.config["filetote"]["extensions"] = ".file"
    env.config["filetote"]["pairing"]["enabled"] = True
    env.config["filetote"]["duplicate_action"] = "keep"
    _activate_plugins()
    observed: list[int] = []

    def observe(
        lib: Library, album: Album | None = None, item: Item | None = None
    ) -> None:
        assert lib is env.lib
        items = list(album.items()) if album is not None else [item]
        for imported in items:
            assert imported is not None
            destination = imported.filepath.parent
            assert (destination / "artifact.file").is_file() is enabled
            assert (destination / f"{imported.filepath.stem}.lrc").is_file() is enabled
            observed.append(imported.id)

    observer = BeetsPlugin("import_observer")
    observer.register_listener(
        "item_imported" if singletons else "album_imported", observe
    )
    assert env.importer is not None
    env.importer.run()
    assert len(observed) == env.media_count
    plugins.send("cli_exit", lib=env.lib)

    for imported in env.lib.items():
        destination = imported.filepath.parent
        assert (destination / "artifact.file").is_file()
        assert (destination / f"{imported.filepath.stem}.lrc").is_file()
        assert not (destination / "artifact.1.file").exists()
    assert (env.import_dir / "the_album" / "artifact.file").exists() is not move


@pytest.mark.parametrize("move", [False, True])
def test_pairing_only_preserves_candidates_for_later_singletons(
    beets_flat_env: BeetsEnvFactory, move: bool
) -> None:
    """Finishing one track does not discard unclaimed pairs for later tracks."""
    env = beets_flat_env(singletons=True, move=move)
    env.config["filetote"]["process_on_import"] = True
    env.config["filetote"]["pairing"]["enabled"] = True
    env.config["filetote"]["pairing"]["pairing_only"] = True
    env.config["filetote"]["duplicate_action"] = "keep"
    _activate_plugins()
    observed: list[int] = []

    def observe(lib: Library, item: Item) -> None:
        assert lib is env.lib
        assert (item.filepath.parent / f"{item.filepath.stem}.lrc").is_file()
        observed.append(item.id)

    BeetsPlugin("import_observer").register_listener("item_imported", observe)
    assert env.importer is not None
    env.importer.run()
    assert len(observed) == env.media_count
    plugins.send("cli_exit", lib=env.lib)
    assert len(list(env.lib_dir.rglob("*.lrc"))) == env.media_count
    assert not list(env.lib_dir.rglob("artifact.file"))


@pytest.mark.parametrize("move", [False, True])
def test_multidisc_extras_available_at_album_imported(
    beets_nested_env: BeetsEnvFactory, move: bool
) -> None:
    """All discs' pairs and parent extras are available before the next listener."""
    env = beets_nested_env(parent_artifacts=["booklet.pdf"], move=move)
    env.config["filetote"]["process_on_import"] = True
    env.config["filetote"]["extensions"] = ".pdf"
    env.config["filetote"]["pairing"]["enabled"] = True
    _activate_plugins()
    observed: list[int] = []

    def observe(lib: Library, album: Album) -> None:
        assert lib is env.lib
        for item in album.items():
            assert (item.filepath.parent / f"{item.filepath.stem}.lrc").is_file()
            observed.append(item.id)
        assert list(env.lib_dir.rglob("booklet.pdf"))

    BeetsPlugin("import_observer").register_listener("album_imported", observe)
    assert env.importer is not None
    env.importer.run()
    assert len(observed) == env.media_count
    plugins.send("cli_exit", lib=env.lib)
    assert len(list(env.lib_dir.rglob("booklet.pdf"))) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_import_completion_leaves_other_collections_pending(
    beets_flat_env: BeetsEnvFactory, reverse: bool
) -> None:
    """Flushing one album preserves other collections and their shared indices."""
    env = beets_flat_env(media_files=[MediaSetup(count=1)])
    env.config["filetote"]["process_on_import"] = True
    env.config["filetote"]["extensions"] = ".file"
    env.config["filetote"]["duplicate_action"] = "keep"
    _activate_plugins()
    filetote = next(p for p in plugins.find_plugins() if p.name == "filetote")
    assert env.importer is not None
    plugins.send("import_begin", session=env.importer)
    albums = []
    for index in range(2):
        source = env.import_dir / f"album{index}"
        source.mkdir()
        medium = env.create_medium(source / "track.mp3")
        env.create_file(source / "extra.file")
        item = Item.from_path(medium.path)
        album = env.lib.add_album([item])
        albums.append(album)
        filetote.collect_artifacts(
            item, item.filepath, env.lib_dir / f"album{index}" / "track.mp3"
        )
    first, second = (1, 0) if reverse else (0, 1)
    plugins.send("album_imported", lib=env.lib, album=albums[first])
    assert (env.lib_dir / f"album{first}" / "extra.file").is_file()
    assert not (env.lib_dir / f"album{second}" / "extra.file").exists()
    plugins.send("album_imported", lib=env.lib, album=albums[second])
    assert (env.lib_dir / f"album{second}" / "extra.file").is_file()
    plugins.send("cli_exit", lib=env.lib)
    assert (env.lib_dir / f"album{second}" / "extra.file").is_file()
    assert not list(env.lib_dir.rglob("extra.1.file"))


@pytest.mark.parametrize("move", [False, True])
def test_grouped_albums_process_shared_extras_once(
    beets_flat_env: BeetsEnvFactory, move: bool
) -> None:
    """Albums sharing a source do not repeatedly process unpaired extras."""
    env = beets_flat_env(media_files=[MediaSetup(count=2)], move=move)
    env.config["filetote"]["process_on_import"] = True
    env.config["filetote"]["extensions"] = ".file"
    env.config["filetote"]["duplicate_action"] = "keep"
    env.config["import"]["group_albums"] = True
    assert env.import_media is not None
    for index, medium in enumerate(env.import_media):
        medium.album = f"Album {index}"
        medium.save()
    _activate_plugins()
    observed: list[bool] = []

    def observe(lib: Library, album: Album) -> None:
        assert lib is env.lib
        item = next(iter(album.items()))
        observed.append((item.filepath.parent / "artifact.file").is_file())

    BeetsPlugin("import_observer").register_listener("album_imported", observe)
    assert env.importer is not None
    env.importer.run()
    assert observed == [True, False]
    plugins.send("cli_exit", lib=env.lib)
    assert len(list(env.lib_dir.rglob("artifact.file"))) == 1
    assert not list(env.lib_dir.rglob("artifact.1.file"))
