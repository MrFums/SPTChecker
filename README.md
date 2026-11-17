## SPT Mod Update Checker

A small Windows app that checks the mods in your SPT install against the [SPT Forge](https://sp-mod.com/mods) and tells you which ones have updates.

Fork of [JoelHauser/SPTChecker](https://github.com/JoelHauser/SPTChecker), cut down to just the installed-mod update check. No tray icon, notifications, startup entry or background polling.

### Use

1. Run `SPTModUpdateChecker.exe`. No Python or .NET install needed.
2. Click **Change** at the bottom and pick your SPT folder: the one holding `BepInEx` and `SPT_Runtime` (or `SPT` on 4.0).
3. The check runs on launch, or click **Check now**.

The headline shows how many mods need updating. The **Updates** tab lists each with installed → latest version; click a row to open its Forge page, or use **Open all**. **Up to date** and **Not on Forge** have their own tabs.

### How it works

- Reads each mod's real metadata (GUID, name, version) from its DLL via .NET reflection, for BepInEx plugins and SPT 4.0/4.1 server mods.
- Matches mods to Forge listings by GUID in batches of 40, then falls back to name search with conservative fuzzy ranking. An unsure match is reported as "Not on Forge", never guessed.
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
