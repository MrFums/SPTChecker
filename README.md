## SPT Mod Update Checker

A small Windows app that checks the mods in your SPT install against the [SPT Forge](https://sp-mod.com/mods) and tells you which ones have updates.

Fork of [JoelHauser/SPTChecker](https://github.com/JoelHauser/SPTChecker), cut down to just the installed-mod update check. No tray icon, notifications, startup entry or background polling.

### Use

1. Run `SPTModUpdateChecker.exe`. No Python or .NET install needed.
2. Click **Change** next to **GAME** and pick your SPT game folder: the one holding `BepInEx` (and `SPT_Runtime`, or `SPT` on 4.0, if the server is there too).
3. If your server runs from a different folder, set **SERVER** to it. Server mods and the SPT version are then read from there.
4. If you run a Fika headless client, it's picked up automatically when it sits in the server folder. If it has its own folder, set **HEADLESS** to it. Its plugins show as **headless**. Network drives work for all three folders.
5. The check runs on launch, or click **Check now**.

A mod installed in several places shows as one row with the version in each place (`game 1.0.1 · server 1.0.1 · headless 1.0.0`). The copies that are behind are highlighted. The **All installs** tab lists every mod with its Game, Server and Headless versions next to the latest on the Forge, so you can confirm an update reached every copy.

The headline shows how many mods need updating. The **Updates** tab lists each with installed → latest version; click a row to open its Forge page, or use **Open all**. **Up to date** and **Not on Forge** have their own tabs.

### How it works

- Reads each mod's real metadata (GUID, name, version) from its DLL via .NET reflection, for BepInEx plugins and SPT 4.0/4.1 server mods.
- Matches mods to Forge listings by GUID in batches of 40, then falls back to name search with conservative fuzzy ranking. An unsure match is reported as "Not on Forge", never guessed. A name match is also dropped when your installed copy is newer than anything that listing has published, since that means it's a different mod.
- Confirms each update with the Forge's own update service for your installed SPT version (read from `SPT.Server.exe`), so incompatible or dependency-blocked releases aren't offered.
- Caches name matches, so a repeat check of about 100 mods takes a few seconds. The first check takes about a minute, because the Forge allows 40 API requests a minute.

A mod can show "Not on Forge" if its internal name differs a lot from its listing, it's part of a pack, or it was removed. A mod can stay "outdated" after updating if its author didn't bump the version compiled into the DLL.

Settings and cache are stored in `%LOCALAPPDATA%\SPTModUpdateChecker`. On first run it picks up your SPT folder from the original SPTChecker, if you had it.

### Build

Needs Python with `requirements.txt` and PyInstaller, plus the .NET 10 SDK if you change `modreader/`.

```bash
python -m pytest tests
```

```bash
python -m PyInstaller --noconfirm SPTModUpdateChecker.spec
```

To rebuild the helper, run `dotnet publish modreader/ModReader.csproj -c Release -o modreader/publish` and copy `ModReader.exe` into `assets/`. Set `SPT41_ROOT` / `SPT40_ROOT` to run the tests against a real install.

### Credits

Original app by JoelHauser. SPT 4.1 server-mod scanning by [scrmjt](https://github.com/scrmjt). The Forge is run by AlexTushonka. Local scanning was inspired by Refringe's **Check Mods**.
