"""Game / server / headless folder handling, without running ModReader."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sptchecker import localmods  # noqa: E402


def _install(root, plugins=(), server_mods=()):
    for name in plugins:
        p = root / "BepInEx" / "plugins" / f"{name}.dll"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    for name in server_mods:
        p = root / "SPT_Runtime" / "user" / "mods" / name / f"{name}.dll"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_headless_resolution(tmp_path):
    game = _install(tmp_path / "game", plugins=["c"])
    server = _install(tmp_path / "server", plugins=["h"], server_mods=["s"])
    bare_server = _install(tmp_path / "bare", server_mods=["s"])
    own = _install(tmp_path / "headless", plugins=["h"])

    resolve = localmods.resolve_headless_root
    assert resolve(game) is None
    assert resolve(game, game) is None
    assert resolve(game, server) == server            # auto: server folder has plugins
    assert resolve(game, bare_server) is None
    assert resolve(game, server, own) == own          # explicit wins
    assert resolve(game, bare_server, own) == own
    assert resolve(game, server, game) is None        # can't be the game's own plugins


def test_scan_reads_each_folder_once_with_its_own_root(tmp_path, monkeypatch):
    game = _install(tmp_path / "game", plugins=["c"], server_mods=["stale"])
    server = _install(tmp_path / "server", server_mods=["s"])
    headless = _install(tmp_path / "headless", plugins=["h"])
    calls = []

    def fake_reader(root, client, server_dlls):
        calls.append((Path(root).name, sorted(Path(p).stem for p in client),
                      sorted(Path(p).stem for p in server_dlls)))
        meta = {str(p): {"guid": f"g.{Path(p).stem}", "version": "1"}
                for p in list(client) + list(server_dlls)}
        return {"client": {k: v for k, v in meta.items() if Path(k).stem in
                           {Path(p).stem for p in client}},
                "server": {k: v for k, v in meta.items() if Path(k).stem in
                           {Path(p).stem for p in server_dlls}}}
    monkeypatch.setattr(localmods, "_run_modreader", fake_reader)

    records = localmods.scan_installed_mods(game, server, headless)

    assert sorted(calls) == [("game", ["c"], []), ("headless", ["h"], []),
                             ("server", [], ["s"])]
    assert sorted((r["source"], r["guid"]) for r in records) == [
        ("client", "g.c"), ("headless", "g.h"), ("server", "g.s")]
