# SPT Mod Update Checker: notes for Claude

Windows app (Python + Tkinter + Pillow, shipped as one PyInstaller exe) that
checks an SPT install's mods against the Forge (sp-mod.com) for updates.
Fork of JoelHauser/SPTChecker with the feed, tray, toasts and registry removed.

## Layout

| Module | Owns |
| --- | --- |
| `main.py` | Launch |
| `sptchecker/checker.py` | The window, its state file, the check thread |
| `sptchecker/localmods.py` | Finding mod DLLs, running ModReader, SPT version |
| `sptchecker/matcher.py` | Matching mods to Forge listings, match cache |
| `sptchecker/feed.py` | All Forge HTTP (rate-limited chokepoint) |
| `sptchecker/theme.py`, `scroll.py` | Drawn widgets (pill buttons, panels, scroll area) |
| `sptchecker/config.py` | Paths, API constants, colours |
| `modreader/` | .NET helper, built with `dotnet publish`, copied to `assets/` |

## Rules

- **Never bypass `feed._forge_request`.** The API allows 50 requests/min per
  IP; we use 40. The maintainer has turned on bot protection before.
- **GUID lookups are batched** (`filter[guid]=a,b,...`, case-insensitive,
  `per_page` capped at 50). Unsettled GUIDs fall back to single lookups.
  Rate-limited ones are `lookup_failed`, never "not on Forge".
- **Match cache** (`match_cache.json`): cache a miss only when the Forge
  provably answered (`_fetch_mods` returns `[]` on network errors too).
- **Tk on Windows:** no canvas anti-aliasing (shapes are Pillow-rendered),
  `tk.Canvas` requests 378px wide unless `width=1`, never shadow `self._w`,
  never hardcode pixel heights for text (fonts scale with DPI), act on a
  button release only after a press on it, and mouse wheel is dispatched
  globally (`scroll._on_global_wheel`).
- **Three folders:** `spt_path` (game, client plugins), optional
  `server_path` (its `SPT_Runtime` mods replace the game folder's stale copy)
  and optional `headless_path`. With no headless set, a separate server
  folder's `BepInEx/plugins` count as the headless
  (`localmods.resolve_headless_root`). ModReader runs once per distinct
  folder so each resolves its own dependencies.
- **ModReader loads dependencies from a stream**, never `LoadFromAssemblyPath`:
  memory-mapping fails with a bare `FileLoadException` on SMB shares. Rebuild
  with `-p:DebugType=None` and copy into `assets/`.
- Comments explain why, using `--` rather than em dashes.

## Verify

- `python -m pytest tests` (set `SPT41_ROOT` for real-install cases).
- UI: build the window offline with stubbed `validate_spt_root`,
  `detect_spt_version`, `_load_state` and `_check`, point `LOCALAPPDATA` at a
  temp dir, and screenshot with `DwmGetWindowAttribute(hwnd, 9)` +
  `ImageGrab`. Raise the window `-topmost` first. **Look at the screenshot.**
- Exe: keep `config.APP_VERSION` and `version_info.py` in step (the exe name
  carries no version). Build with `python -m PyInstaller --noconfirm
  SPTModUpdateChecker.spec`, check the `dist/` timestamp, then launch it with
  a temp `LOCALAPPDATA` and confirm `SPTModUpdateChecker\settings.json` gets a
  `checked_at`. Kill the whole process tree.

## State

- 1.0.0 (2026-11-17): renamed SPT Mod Update Checker, own icon and graphite
  and teal theme, data in `%LOCALAPPDATA%\SPTModUpdateChecker` (migrates the
  SPT folder and match cache from the old `SPTModChecker` folder). Batched GUID
  lookups plus the match cache take a 101-mod install from ~3.5 min to 60s
  cold / 3s warm.
