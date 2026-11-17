import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

_VERSION_PART_RE = re.compile(r"\d+")


def parse_version(v):
    """Dotted version string -> tuple of ints, or None if nothing
    version-shaped. "V3.3.1" and "3.3.1" parse the same."""
    if not v:
        return None
    parts = _VERSION_PART_RE.findall(v)
    return tuple(int(p) for p in parts) if parts else None


def pad_versions(a, b):
    """Zero-pad so (1, 0, 2) and (1, 0, 2, 0) compare equal."""
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def is_newer(available, current):
    """True only if `available` is numerically greater. A string inequality
    would call a downgrade an update; unparseable versions count as no update."""
    a, c = parse_version(available), parse_version(current)
    if a is None or c is None:
        return False
    a, c = pad_versions(a, c)
    return a > c


def parse_dt(ts_str):
    """Parse an ISO or RFC 2822 timestamp into an aware datetime, or None."""
    if not ts_str:
        return None
    try:
        try:
            dt = parsedate_to_datetime(ts_str)
        except Exception:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
