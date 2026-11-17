"""Forge (sp-mod.com) API lookups, all through one rate-limited chokepoint."""
import threading
import time
from collections import deque
from datetime import datetime, timezone

import requests

from .config import (
    API_MODS_UPDATES_URL, API_URL, APP_VERSION, GUID_LOOKUP_CHUNK_SIZE,
    MODS_UPDATES_CHUNK_SIZE,
)
from .utils import parse_dt

_session = requests.Session()
_session.headers["User-Agent"] = f"SPTModChecker/{APP_VERSION}"
_API_HEADERS = {"Accept": "application/json"}

# sp-mod.com allows 50 API requests/minute per IP and times you out for a
# minute past that. Stay under it: the user's browser may share the IP.
_API_RATE_LIMIT = 40
_RATE_WINDOW_SECONDS = 60.0
# Smooths bursts, so a scan doesn't spend a minute's budget in ten seconds
# and then sit frozen.
_REQUEST_MIN_INTERVAL = 0.25
# Cap on one Retry-After wait; the API's own penalty is one minute.
_RETRY_AFTER_MAX = 90.0

_throttle_lock = threading.Lock()
_last_request_ts = 0.0


class _RateLimiter:
    """Sliding window: at most `limit` requests in any `window` seconds."""

    def __init__(self, limit, window):
        self._limit, self._window = limit, window
        self._hits = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                cutoff = time.monotonic() - self._window
                while self._hits and self._hits[0] <= cutoff:
                    self._hits.popleft()
                if len(self._hits) < self._limit:
                    self._hits.append(time.monotonic())
                    return
                wait = self._hits[0] - cutoff
            time.sleep(max(wait, 0.05))


_api_limiter = _RateLimiter(_API_RATE_LIMIT, _RATE_WINDOW_SECONDS)


class ForgeBlocked(Exception):
    """Cloudflare served a bot challenge. Retrying can't fix it."""


class ForgeRateLimited(Exception):
    """429s outlasted the retries. Means "unknown", never "not on the Forge"."""


def _is_challenge(resp):
    if resp.headers.get("Cf-Mitigated", "").lower() == "challenge":
        return True
    return (resp.status_code in (403, 503)
            and resp.headers.get("Server", "").lower() == "cloudflare"
            and "text/html" in resp.headers.get("Content-Type", ""))


def _retry_after_seconds(resp):
    """Retry-After may be seconds or an HTTP date."""
    value = resp.headers.get("Retry-After", "")
    try:
        seconds = float(value)
    except ValueError:
        when = parse_dt(value)
        seconds = (when - datetime.now(timezone.utc)).total_seconds() if when else 2.0
    return max(0.0, min(seconds, _RETRY_AFTER_MAX))


def _forge_request(method, url, retries=3, **kw):
    """Every Forge request goes through here: rate limit, pacing, 429 retry.
    Raises ForgeBlocked on a challenge, ForgeRateLimited once retries run out;
    otherwise returns the response unchecked."""
    global _last_request_ts
    for attempt in range(retries + 1):
        _api_limiter.acquire()
        with _throttle_lock:
            wait = _REQUEST_MIN_INTERVAL - (time.monotonic() - _last_request_ts)
            if wait > 0:
                time.sleep(wait)
            _last_request_ts = time.monotonic()
        resp = _session.request(method, url, **kw)
        if _is_challenge(resp):
            raise ForgeBlocked("sp-mod.com is blocking automated requests (Cloudflare challenge)")
        if resp.status_code != 429:
            return resp
        if attempt == retries:
            raise ForgeRateLimited("sp-mod.com is rate limiting this client")
        time.sleep(_retry_after_seconds(resp))


def _parse_api_mod(item):
    versions = item.get("versions") or []
    latest = versions[0] if versions else {}
    return {
        "title": item.get("name", ""),
        "slug": item.get("slug", ""),
        "link": item.get("detail_url", ""),
        "guid": item.get("guid", ""),
        "author": (item.get("owner") or {}).get("name", "Unknown"),
        "version": latest.get("version", ""),
        "category": (item.get("category") or {}).get("title", ""),
    }


def _fetch_mods(params, timeout=15):
    """One page of /mods; [] on ordinary failures. ForgeBlocked and
    ForgeRateLimited propagate: they mean "unknown", not "no results"."""
    try:
        resp = _forge_request("get", API_URL, params={"include": "versions,category", **params},
                              headers=_API_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return [_parse_api_mod(item) for item in resp.json().get("data", [])]
    except (ForgeBlocked, ForgeRateLimited):
        raise
    except Exception:
        return []


def lookup_by_guid(guid):
    """Exact GUID match (case-insensitive), or None if none or ambiguous."""
    if not guid:
        return None
    mods = _fetch_mods({"filter[guid]": guid})
    if len(mods) != 1 or (mods[0].get("guid") or "").casefold() != guid.casefold():
        return None
    return mods[0]


def lookup_by_guids(guids):
    """Batch form of lookup_by_guid: filter[guid] takes a comma-separated
    list, so one request covers GUID_LOOKUP_CHUNK_SIZE mods.

    Returns (found, absent, failed), keyed by casefolded GUID:
    - found: {guid: mod} where exactly one listing has that GUID.
    - absent: the Forge answered and no single listing has it.
    - failed: the chunk was rate limited (unknown, not missing).
    A GUID in none of these wasn't settled (empty page, which _fetch_mods also
    returns on a network error, or a full page that may have cut it off), and
    callers fall back to lookup_by_guid for it.
    """
    wanted = list(dict.fromkeys(g.casefold() for g in guids if g and "," not in g))
    found, absent, failed = {}, set(), set()
    for i in range(0, len(wanted), GUID_LOOKUP_CHUNK_SIZE):
        chunk = wanted[i:i + GUID_LOOKUP_CHUNK_SIZE]
        try:
            mods = _fetch_mods({"filter[guid]": ",".join(chunk), "per_page": 50})
        except ForgeRateLimited:
            failed.update(chunk)
            continue
        if not mods or len(mods) >= 50:
            continue
        by_guid = {}
        for mod in mods:
            by_guid.setdefault((mod.get("guid") or "").casefold(), []).append(mod)
        for guid in chunk:
            hits = by_guid.get(guid, [])
            if len(hits) == 1:
                found[guid] = hits[0]
            else:
                absent.add(guid)
    return found, absent, failed


def lookup_by_name(name):
    """filter[name]: matches only when `name` is a substring of the title."""
    return _fetch_mods({"filter[name]": name, "per_page": 20}) if name else []


def lookup_by_query(term):
    """query=: undocumented fuzzy full-text search. Looser; rank the results."""
    return _fetch_mods({"query": term, "per_page": 20}) if term else []


def lookup_updates(pairs, spt_version):
    """The Forge's own verdict on (guid, installed_version) pairs for this SPT
    version: knows about SPT compatibility and dependency blocks, which a plain
    version comparison can't. Returns the merged buckets updates,
    blocked_updates, up_to_date, incompatible_with_spt. A failed chunk is
    skipped, so callers treat "in no bucket" as "no verdict"."""
    merged = {"updates": [], "blocked_updates": [], "up_to_date": [], "incompatible_with_spt": []}
    if not pairs or not spt_version:
        return merged
    for i in range(0, len(pairs), MODS_UPDATES_CHUNK_SIZE):
        chunk = pairs[i:i + MODS_UPDATES_CHUNK_SIZE]
        try:
            resp = _forge_request("get", API_MODS_UPDATES_URL,
                                  params={"mods": ",".join(f"{g}:{v}" for g, v in chunk),
                                          "spt_version": spt_version},
                                  headers=_API_HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except Exception:
            continue
        for key in merged:
            merged[key].extend(data.get(key, []))
    return merged
