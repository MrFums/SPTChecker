"""Batched GUID lookup: one request per chunk must give the same answers the
old one-request-per-mod lookup did."""
import pytest

from sptchecker import feed, matcher


def _mod(guid, title="T", version="1.0.0"):
    return {"guid": guid, "title": title, "slug": title.lower(), "link": f"x/{guid}",
            "version": version, "author": "a"}


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    def install(responder):
        def fetch(params, **kw):
            calls.append(params)
            return responder(params)
        monkeypatch.setattr(feed, "_fetch_mods", fetch)
        return calls
    return install


def test_maps_by_casefold_and_flags_ambiguous(fake_fetch):
    calls = fake_fetch(lambda p: [_mod("Com.A"), _mod("com.dup"), _mod("com.dup")])
    found, absent, failed = feed.lookup_by_guids(["com.a", "COM.A", "com.dup", "com.none"])
    assert len(calls) == 1
    assert calls[0]["filter[guid]"] == "com.a,com.dup,com.none"
    assert found["com.a"]["guid"] == "Com.A"
    assert absent == {"com.dup", "com.none"}
    assert not failed


def test_chunks_requests(fake_fetch, monkeypatch):
    monkeypatch.setattr(feed, "GUID_LOOKUP_CHUNK_SIZE", 2)
    calls = fake_fetch(lambda p: [_mod(g) for g in p["filter[guid]"].split(",")])
    found, _, _ = feed.lookup_by_guids(["a", "b", "c"])
    assert len(calls) == 2
    assert set(found) == {"a", "b", "c"}


def test_rate_limited_chunk_is_failed_not_absent(fake_fetch):
    def boom(p):
        raise feed.ForgeRateLimited("x")
    fake_fetch(boom)
    found, absent, failed = feed.lookup_by_guids(["a"])
    assert failed == {"a"} and not found and not absent


def test_empty_or_full_page_settles_nothing(fake_fetch):
    fake_fetch(lambda p: [])
    assert feed.lookup_by_guids(["a"]) == ({}, set(), set())
    fake_fetch(lambda p: [_mod(f"g{i}") for i in range(50)])
    assert feed.lookup_by_guids(["a"]) == ({}, set(), set())


def test_blocked_propagates(fake_fetch):
    def blocked(p):
        raise feed.ForgeBlocked("x")
    fake_fetch(blocked)
    with pytest.raises(feed.ForgeBlocked):
        feed.lookup_by_guids(["a"])


def test_match_one_uses_batch(monkeypatch):
    def no_single(guid):
        raise AssertionError("single GUID lookup should not run")
    monkeypatch.setattr(matcher, "lookup_by_guid", no_single)
    monkeypatch.setattr(matcher, "lookup_by_name", lambda n: [])
    monkeypatch.setattr(matcher, "lookup_by_query", lambda t: [])
    batch = ({"com.a": _mod("com.a", version="2.0.0")}, {"com.miss"}, {"com.fail"})

    hit = matcher.match_one({"guid": "COM.A", "name": "A", "version": "1.0.0"}, batch)
    assert hit["match_method"] == "guid" and hit["update_available"]

    miss = matcher.match_one({"guid": "com.miss", "name": "Miss", "version": "1"}, batch)
    assert miss["forge"] is None and not miss["lookup_failed"]

    fail = matcher.match_one({"guid": "com.fail", "name": "F", "version": "1"}, batch)
    assert fail["lookup_failed"]


def test_cache_skips_searches_on_second_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher, "MATCH_CACHE_FILE", tmp_path / "c.json")
    listing = _mod("forge.real", title="Real Mod", version="2.0.0")
    searches = []

    def by_guids(guids):
        keys = {g.casefold() for g in guids if g}
        found = {"forge.real": listing} if "forge.real" in keys else {}
        return found, keys - set(found), set()
    monkeypatch.setattr(matcher, "lookup_by_guids", by_guids)
    monkeypatch.setattr(matcher, "lookup_by_name",
                        lambda n: searches.append(n) or ([listing] if "Real" in n else []))
    monkeypatch.setattr(matcher, "lookup_by_query", lambda t: searches.append(t) or [])
    mods = [{"guid": "local.real", "name": "Real Mod", "version": "1.0.0"},
            {"guid": "local.gone", "name": "Gone", "version": "1.0.0"}]

    first = matcher.match_local_mods(mods)
    assert searches  # cold scan has to search
    searches.clear()
    second = matcher.match_local_mods(mods)
    assert searches == []
    assert [r["forge"] and r["forge"]["guid"] for r in second] == ["forge.real", None]
    assert second[0]["update_available"] and second[0]["match_method"] == "cached"
    assert [r["forge"] for r in first][0]["guid"] == "forge.real"


def test_unsettled_miss_is_not_cached(monkeypatch, tmp_path):
    cache_file = tmp_path / "c.json"
    monkeypatch.setattr(matcher, "MATCH_CACHE_FILE", cache_file)
    # Batch settled nothing (as on a network error) and every search came back empty.
    monkeypatch.setattr(matcher, "lookup_by_guids", lambda g: ({}, set(), set()))
    monkeypatch.setattr(matcher, "lookup_by_guid", lambda g: None)
    monkeypatch.setattr(matcher, "lookup_by_name", lambda n: [])
    monkeypatch.setattr(matcher, "lookup_by_query", lambda t: [])
    matcher.match_local_mods([{"guid": "local.x", "name": "X", "version": "1"}])
    assert matcher._load_cache() == {}


def test_same_mod_in_several_installs_searched_once_and_merged(monkeypatch, tmp_path):
    monkeypatch.setattr(matcher, "MATCH_CACHE_FILE", tmp_path / "c.json")
    listing = _mod("forge.x", title="X Mod", version="2.0.0")
    searches = []
    monkeypatch.setattr(matcher, "lookup_by_guids",
                        lambda g: ({}, {x.casefold() for x in g if x}, set()))
    monkeypatch.setattr(matcher, "lookup_by_name",
                        lambda n: searches.append(n) or [listing])
    mods = [{"guid": "local.x", "name": "X Mod", "version": "2.0.0", "source": "client"},
            {"guid": "local.x", "name": "X Mod", "version": "1.0.0", "source": "headless"}]
    [r] = matcher.match_local_mods(mods)
    assert len(searches) == 1
    assert r["sources"] == ["client", "headless"]
    assert r["outdated_sources"] == ["headless"] and r["update_available"]
    assert r["current_version"] == "client 2.0.0, headless 1.0.0"
    assert r["available_version"] == "2.0.0"
    assert r["versions"] == {"client": "2.0.0", "headless": "1.0.0"}


def test_unmatched_mod_in_several_installs_is_one_row():
    def miss(guid, source, version="1.0.0"):
        return {"local": {"guid": guid, "name": "N", "source": source, "version": version},
                "forge": None, "match_method": None, "current_version": version,
                "available_version": None, "update_available": False, "lookup_failed": False}
    merged = matcher.merge_duplicate_matches(
        [miss("com.x", "client"), miss("COM.X", "headless", "0.9"), miss("com.y", "client")])
    assert len(merged) == 2
    assert merged[0]["versions"] == {"client": "1.0.0", "headless": "0.9"}


def test_name_match_older_than_installed_is_rejected():
    listing = _mod("forge.other", title="Configuration Manager Input Fix", version="1.0.0")
    mod = {"guid": "com.bepis.cm", "name": "Configuration Manager", "version": "18.4"}
    assert matcher._result(mod, listing, "fuzzy")["forge"] is None
    assert matcher._result(mod, listing, "cached")["forge"] is None
    # An exact GUID match is trusted even when the Forge lags behind.
    assert matcher._result(mod, listing, "guid")["forge"] is listing


def test_match_one_falls_back_when_unsettled(monkeypatch):
    seen = []
    monkeypatch.setattr(matcher, "lookup_by_guid", lambda g: seen.append(g) or _mod(g))
    r = matcher.match_one({"guid": "com.x", "name": "X", "version": "1.0.0"}, ({}, set(), set()))
    assert seen == ["com.x"] and r["match_method"] == "guid"
