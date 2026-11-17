import os
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────

_BUNDLE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent
ASSETS_DIR = _BUNDLE_DIR / "assets"
APP_NAME = "SPT Mod Update Checker"
_LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home()))
DATA_DIR = _LOCAL / "SPTModUpdateChecker"
# The original SPTChecker's folder: read once to carry the SPT folder and
# match cache over, so the first check after switching is a warm one.
LEGACY_DATA_DIR = _LOCAL / "SPTModChecker"

# Sent in the User-Agent and stamped on the exe (version_info.py).
APP_VERSION = "1.0.0"

# ── Forge API ──────────────────────────────────────────────────────────

API_URL = "https://sp-mod.com/api/v0/mods"
API_MODS_UPDATES_URL = "https://sp-mod.com/api/v0/mods/updates"
# Both endpoints take comma-separated lists; chunked to stay under the API's
# 50-per-page cap (so a GUID with two listings can't push another off the
# page) and to keep the request line short.
GUID_LOOKUP_CHUNK_SIZE = 40
MODS_UPDATES_CHUNK_SIZE = 40
# Name-search results are cached so repeat scans skip them. Hits are
# re-confirmed each scan inside the GUID batch; misses expire after a week so
# a mod that gets listed later is picked up.
MATCH_CACHE_FILE = DATA_DIR / "match_cache.json"
MATCH_MISS_TTL_DAYS = 7
FUZZY_MATCH_THRESHOLD = 0.82

# ── SPT install layout ─────────────────────────────────────────────────

# Client plugins live at the game root in every version.
BEPINEX_PLUGINS_SUBPATH = "BepInEx/plugins"
# SPT 4.1 renamed the server folder "SPT" -> "SPT_Runtime"; check both, since
# an in-place upgrade can leave the old one behind.
SERVER_DIR_NAMES = ("SPT_Runtime", "SPT")
SERVER_MODS_SUBPATHS = tuple(f"{d}/user/mods" for d in SERVER_DIR_NAMES)
SPT_SERVER_EXE_SUBPATHS = tuple(f"{d}/SPT.Server.exe" for d in SERVER_DIR_NAMES)
# Pre-v4 server mods (package.json manifests) at the game root. Matched only
# on that manifest shape: v4 DLLs here are the 4.1 mod-manager bug's dead mods.
LEGACY_SERVER_MODS_SUBPATH = "user/mods"
# SPT's own bundled DLLs (SPT.Common, ...) look like mods but aren't on the Forge.
CORE_SPT_NAME_PREFIX = "spt."
# .NET helper that reads mod metadata via real reflection; built separately
# (see modreader/) and copied into assets/.
MODREADER_EXE = ASSETS_DIR / "ModReader.exe"
MODREADER_TIMEOUT_SECONDS = 120

# ── Colors ─────────────────────────────────────────────────────────────

# Neutral graphite with a teal accent: chrome bars sit lighter than the body.
BG = "#141516"            # window body
STATUS_BG = "#1c1d1f"     # header and footer bars
CARD_BG = "#202123"       # hovered row, inputs, buttons
CARD_HOVER = "#2a2b2e"
SEPARATOR = "#26272a"
BORDER = "#36383c"

TEXT_BRIGHT = "#f4f4f5"
TEXT = "#c9cacd"
TEXT_DIM = "#8b8d93"
TEXT_FAINT = "#5f6167"

ACCENT_NEW = "#2ec4b6"     # teal: primary action, up to date
ACCENT_UPD = "#ff7a45"     # coral: update available
ACCENT_DANGER = "#e5484d"

CARD_RADIUS = 6
