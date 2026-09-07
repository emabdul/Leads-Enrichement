"""Apple App Store lookup, via the public iTunes Search API.

Mirrors matcher.find_app so both stores return the same shape.

Two quirks drive the design:

* On a non-US storefront the API returns *localised* titles - searching KR
  gives back "햄도쿠: 스도쿠 논리 퍼즐", which cannot be matched against the
  English text on a card. Passing lang=en_us forces English.
* Apple's search index misses brand-new apps just like Play's does. The way
  around it is the artist lookup, which lists a developer's whole catalogue.
  Unlike Play's developer page this is reachable from a *truncated* publisher
  name, because the name only has to be good enough for search to rank the
  developer - see _publisher_ladder.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional, Tuple

import requests

from matcher import Candidate, _field_score, query_variants

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"
ITUNES_LANG = "en_us"  # force English titles regardless of storefront


def _get(url: str, params: dict, timeout: int = 25) -> dict:
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    # Apple sometimes serves JSON as text/javascript.
    return resp.json()


def _to_candidate(raw: dict) -> Optional[Candidate]:
    track_id = raw.get("trackId")
    if not track_id:
        return None
    return Candidate(
        app_id=str(track_id),
        title=raw.get("trackName") or "",
        developer=raw.get("artistName") or "",
        store="appstore",
        url_override=(raw.get("trackViewUrl") or "").split("?")[0],
        developer_url=(raw.get("artistViewUrl") or "").split("?")[0],
        developer_id=str(raw.get("artistId") or ""),
    )


def _publisher_ladder(publisher: str, limit: int = 3) -> List[str]:
    """Publisher name with the trailing (often partial) word dropped, repeatedly.

    A card showing "LeoGame Co., Lt" finds nothing, but "LeoGame Co." ranks the
    right developer first. Punctuation is stripped for the same reason.
    """
    cleaned = re.sub(r"[,:;|]+", " ", publisher or "")
    words = re.sub(r"\s+", " ", cleaned).strip().split()
    out: List[str] = []
    while words and len(out) < limit:
        term = " ".join(words)
        if term and term not in out:
            out.append(term)
        words = words[:-1]
    return out


def artist_candidates(
    publisher: str, country: str = "us", limit: int = 200, verbose: bool = False
) -> List[Candidate]:
    """Every app by the developer whose name best matches `publisher`."""
    key = re.sub(r"[^a-z0-9]", "", (publisher or "").lower())
    if len(key) < 4:
        return []

    for term in _publisher_ladder(publisher):
        try:
            results = _get(SEARCH_URL, {
                "term": term, "entity": "software", "country": country,
                "limit": 25, "lang": ITUNES_LANG,
            }).get("results", [])
        except Exception as exc:
            if verbose:
                print(f"      itunes artist search {term!r} failed: {exc}")
            continue

        artist_ids = {}
        for raw in results:
            name = re.sub(r"[^a-z0-9]", "", (raw.get("artistName") or "").lower())
            # The card name is a prefix of the real one, not the reverse.
            if name and name.startswith(key[:10]):
                artist_ids[raw.get("artistId")] = raw.get("artistName")
        if not artist_ids:
            continue

        out: List[Candidate] = []
        for artist_id in list(artist_ids)[:2]:
            try:
                got = _get(LOOKUP_URL, {
                    "id": str(artist_id), "entity": "software",
                    "country": country, "limit": limit, "lang": ITUNES_LANG,
                }).get("results", [])
            except Exception:
                continue
            for raw in got:
                if raw.get("wrapperType") != "software":
                    continue
                cand = _to_candidate(raw)
                if cand:
                    out.append(cand)
        if verbose:
            print(f"      itunes artist {term!r} -> {len(out)} app(s) "
                  f"from {list(artist_ids.values())}")
        if out:
            return out
    return []


def artist_apps_by_id(artist_id: str, country: str = "us",
                      limit: int = 200) -> List[Candidate]:
    """Every app by a developer, addressed by their numeric artist id.

    Exact where a name search is not: "汪 陶" returns nothing when searched
    for as text, but its artist id lists the catalogue fine.
    """
    if not artist_id:
        return []
    try:
        got = _get(LOOKUP_URL, {"id": str(artist_id), "entity": "software",
                                "country": country, "limit": limit,
                                "lang": ITUNES_LANG}).get("results", [])
    except Exception:
        return []
    out = []
    for raw in got:
        if raw.get("wrapperType") != "software":
            continue
        cand = _to_candidate(raw)
        if cand:
            out.append(cand)
    return out


def find_app(
    card,
    lang: str = "en",
    country: str = "us",
    hits: int = 5,
    max_queries: int = 3,
    delay: float = 0.6,
    verbose: bool = False,
    deep: bool = True,
) -> Tuple[Optional[Candidate], List[Candidate], List[str]]:
    country = (getattr(card, "country", "") or country).lower()
    # A card's country badge is an ad-targeting region, not necessarily a
    # storefront that searches well: "vn" returns zero results for terms the
    # "us" storefront resolves fine. Fall back to us, which carries most apps.
    storefronts = [country] + (["us"] if country != "us" else [])

    problems: List[str] = []
    pool: dict = {}

    for store_country in storefronts:
        for i, term in enumerate(
            query_variants(card.title, card.publisher)[:max_queries]
        ):
            if i:
                time.sleep(delay)
            try:
                results = _get(SEARCH_URL, {
                    "term": term, "entity": "software", "country": store_country,
                    "limit": hits, "lang": ITUNES_LANG,
                }).get("results", [])
            except Exception as exc:
                problems.append(f"itunes query {term!r} failed: "
                                f"{type(exc).__name__}: {exc}")
                continue
            if verbose:
                print(f"      itunes query {term!r} [{store_country}] "
                      f"-> {len(results)} hits")
            for raw in results:
                cand = _to_candidate(raw)
                if cand and cand.app_id not in pool:
                    pool[cand.app_id] = cand
        if pool:
            break

    def rescore():
        for c in pool.values():
            c.title_score = _field_score(card.title, c.title, card.title_truncated)
            c.dev_score = (
                _field_score(card.publisher, c.developer, card.publisher_truncated)
                if card.publisher else 0.0
            )
            c.score = (0.55 * c.title_score + 0.45 * c.dev_score
                       if card.publisher else c.title_score)

    rescore()
    best_so_far = max((c.score for c in pool.values()), default=0.0)

    # Apple's search index misses new listings; the developer's catalogue does not.
    if deep and best_so_far < 0.85 and card.publisher:
        if verbose:
            print(f"      weak itunes match ({best_so_far:.2f}), trying artist lookup")
        for store_country in storefronts:
            found = artist_candidates(card.publisher, store_country, verbose=verbose)
            if found:
                for cand in found:
                    pool.setdefault(cand.app_id, cand)
                rescore()
                break

    ranked = sorted(pool.values(), key=lambda c: c.score, reverse=True)
    return (ranked[0] if ranked else None), ranked[:5], problems


def search_url(title: str, publisher: str = "", country: str = "us") -> str:
    """A human-checkable App Store search link."""
    from urllib.parse import quote_plus

    term = re.sub(r"\s+", " ", f"{title} {publisher}".strip())
    return f"https://www.apple.com/{country}/search/{quote_plus(term)}?src=serp"


def lookup_by_id(track_id: str, country: str = "us") -> Optional[Candidate]:
    """Resolve a known numeric App Store id directly - no searching involved."""
    try:
        results = _get(LOOKUP_URL, {
            "id": str(track_id), "country": country, "lang": ITUNES_LANG,
        }).get("results", [])
    except Exception:
        return None
    for raw in results:
        cand = _to_candidate(raw)
        if cand:
            return cand
    return None
