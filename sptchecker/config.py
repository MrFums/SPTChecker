import os
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────

_BUNDLE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent
ASSETS_DIR = _BUNDLE_DIR / "assets"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SPTModChecker"
# The old feed app's state file; read once to carry the SPT folder over.
STATE_FILE = DATA_DIR / "spt_mods_state.json"

# Keep in step with version_info.py and the .spec filename/name.
APP_VERSION = "4.0.0"

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

BG = "#101219"            # window background
STATUS_BG = "#0b0d13"     # header and footer bars
CARD_BG = "#1a1d27"       # raised surfaces
CARD_HOVER = "#262b3a"
SEPARATOR = "#262b38"
BORDER = "#2f3545"

TEXT_BRIGHT = "#eef0f6"
TEXT = "#bcc2d2"
TEXT_DIM = "#828ba1"
TEXT_FAINT = "#5b6377"

ACCENT_NEW = "#4ad07f"     # up to date / primary action
ACCENT_UPD = "#f2a53c"     # update available
ACCENT_DANGER = "#ef5350"

CARD_RADIUS = 8
